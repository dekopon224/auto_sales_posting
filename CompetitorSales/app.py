import boto3
import json
import re
import hashlib
from datetime import datetime, timedelta, timezone
import time
from playwright.sync_api import sync_playwright
from urllib.parse import urlparse, parse_qs

# DynamoDB テーブル名
TABLE_NAME = 'CompetitorSales'

def lambda_handler(event, context):
    # SQSメッセージから URLs パラメータ取得
    all_urls = []
    timestamps = []
    
    if 'Records' in event:
        # SQSイベントの場合
        for record in event['Records']:
            try:
                message_body = json.loads(record['body'])
                urls = message_body.get('urls', [])
                timestamp = message_body.get('timestamp', '')
                if urls and isinstance(urls, list):
                    all_urls.extend(urls)
                    timestamps.append(timestamp)
            except Exception as e:
                print(f"SQSメッセージ解析エラー: {e}")
                continue
    else:
        # 既存のHTTPリクエスト処理（互換性維持）
        if 'body' in event:
            body = json.loads(event['body'] or '{}')
            urls = body.get('urls')
        else:
            urls = event.get('urls')
        if urls and isinstance(urls, list):
            all_urls = urls
    
    if not all_urls:
        return { 'statusCode': 400, 'body': json.dumps({'error': 'urls (リスト) が必要です'}) }

    results = []
    errors = []  # エラー情報を記録
    
    for url in all_urls:
        # スクレイピング
        reservation_data = get_reservation_data(url)
        if 'error' in reservation_data:
            # エラーでも処理を続行
            errors.append({
                'url': url,
                'error': reservation_data['error']
            })
            continue  # 次のURLへ
        
        # DynamoDB へ保存
        try:
            write_to_dynamodb(url, reservation_data)
            results.append(reservation_data)
        except Exception as e:
            errors.append({
                'url': url,
                'error': f"DynamoDB書き込み失敗: {e}"
            })
    
    # 部分的成功でも200を返す
    if results:
        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': f'{len(results)}件保存完了',
                'successful': len(results),
                'failed': len(errors),
                'records': results,
                'errors': errors
            }, ensure_ascii=False)
        }
    else:
        # 全て失敗した場合のみ500
        return {
            'statusCode': 500,
            'body': json.dumps({
                'error': '全てのURL処理に失敗',
                'errors': errors
            }, ensure_ascii=False)
        }


def write_to_dynamodb(url, data):
    """
    reservation_data の構造
      {
        'url': ...,
        'plans': [ {'name': planDisplayName, 'price': priceStr, 'id': planId}, ... ],
        'reserved_times': { '5月17日': [ {...}, … ], … },
        'timestamp': '2025-05-16T08:00:00+09:00',
        'name': space_name,
        'space_id': space_id
      }
    を展開して、CompetitorSales テーブルへ put_item します。
    """
    dynamo = boto3.resource('dynamodb')
    table = dynamo.Table(TABLE_NAME)

    # URLからroomIdを抽出（両方のURL形式に対応）
    room_match = re.search(r'/p/([^/?]+)', url)
    if room_match:
        room_uid = room_match.group(1)
    else:
        # 新しいURL形式の場合、クエリパラメータから取得
        parsed_url = urlparse(url)
        query_params = parse_qs(parsed_url.query)
        room_uid = query_params.get('room_uid', [None])[0]

    # spaceId はJSONから取得したものを使用
    space_id = data.get('space_id', 'unknown')

    JST = timezone(timedelta(hours=9))
    now_jst = datetime.now(JST)
    
    # 🔧 TTL設定: 3年後の削除時刻を計算
    ttl_date = now_jst + timedelta(days=365 * 3)  # 3年後
    ttl_timestamp = int(ttl_date.timestamp())  # Unix timestamp

    # 現在時刻が0時以降か12時以降かを判定
    current_hour = now_jst.hour
    if current_hour < 12:
        # 0時以降12時未満の場合、0時以降の時間帯のみ処理
        time_threshold = now_jst.replace(hour=0, minute=0, second=0, microsecond=0)
    else:
        # 12時以降の場合、12時以降の時間帯のみ処理
        time_threshold = now_jst.replace(hour=12, minute=0, second=0, microsecond=0)

    for plan in data['plans']:
        disp_name = plan['name']
        price = int(re.sub(r'\D', '', plan['price'])) if plan['price'] else 0
        plan_id = plan.get('id', '')

        for formatted_date, ranges in data['reserved_times'].items():
            date_match = re.match(r'(\d+)月(\d+)日', formatted_date)
            if not date_match:
                continue  # スキップ
            m, d = map(int, date_match.groups())
            # 年跨ぎ対応版
            year = now_jst.year
            if m < now_jst.month or (m == now_jst.month and d < now_jst.day):
                year += 1  # 翌年として扱う
            reservation_date = f"{year}-{m:02d}-{d:02d}"

            for slot in ranges:
                start_hour, start_minute = map(int, slot['start_time'].split(':'))
                end_hour, end_minute = map(int, slot['end_time'].split(':'))
                if end_hour < start_hour:
                    end_hour += 24
                
                # 予約時間がtime_thresholdより前の場合はスキップ（過去時間の除外）
                slot_datetime = datetime.strptime(reservation_date, "%Y-%m-%d").replace(tzinfo=JST)
                slot_datetime = slot_datetime.replace(hour=start_hour, minute=start_minute)
                if start_hour >= 24:
                    slot_datetime += timedelta(days=1)
                    slot_datetime = slot_datetime.replace(hour=start_hour - 24, minute=start_minute)
                
                if slot_datetime < time_threshold:
                    continue
                
                sk = f"{plan_id}#{reservation_date}#{slot['start_time']}"

                start_minutes = start_hour * 60 + start_minute
                end_minutes = end_hour * 60 + end_minute
                usage_hours = (end_minutes - start_minutes) / 60
                total_price = int(price * usage_hours)

                item = {
                    'spaceId':         space_id,
                    'sortKey':         sk,
                    'planId':          plan_id,
                    'planDisplayName': disp_name,
                    'reservationDate': reservation_date,
                    'start_time':      slot['start_time'],
                    'end_time':        slot['end_time'],
                    'price':           total_price,
                    'created_at':      now_jst.isoformat(),
                    'processed_at':    now_jst.isoformat(),
                    'url':             data['url'],
                    'name':            data.get('name', ''),
                    'ttl': ttl_timestamp  # 3年後の削除時刻
                }
                table.put_item(Item=item)


def get_reservation_data(original_url):
    """Playwrightを使用して、トップページ→予約ページと遷移後に予約情報とプラン情報を取得する関数"""
    # メモリリークを防ぐため、最初に宣言
    browser = None
    page = None
    
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--single-process",
                    "--no-zygote",
                    "--no-sandbox",
                    "--disable-gpu",
                    "--disable-dev-shm-usage",
                    "--headless=new",
                    "--disable-http2",
                ]
            )
            # コンテキストを作らず、直接ページを作成
            page = browser.new_page()
            
            # user_agentを設定
            page.set_extra_http_headers({
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/112.0.0.0 Safari/537.36"
            })

            # URL形式を判定して、roomUidとspaceIdを抽出
            room_match = re.search(r'/p/([^/?]+)', original_url)
            space_match_direct = re.search(r'/spaces/([^/?]+)', original_url)
            
            if room_match:
                # 既存の /p/ 形式
                room_uid = room_match.group(1)
                
                # 1) トップページにアクセス（リダイレクト後の URL を取得）
                resp = page.goto(original_url, wait_until='networkidle', timeout=90000)
                if not resp.ok:
                    return {'error': f"ページロードエラー: {resp.status} {resp.status_text}"}
                page.wait_for_load_state("networkidle")
                time.sleep(2)

                # 2) spaceId を抽出
                redirected = page.url  # e.g. https://www.spacemarket.com/spaces/<spaceId>/?...
                space_match = re.search(r'/spaces/([^/]+)/', redirected)
                if not space_match:
                    return {'error': 'spaceId の抽出失敗'}
                space_id_from_url = space_match.group(1)
                
            elif space_match_direct:
                # 新しい /spaces/ 形式
                space_id_from_url = space_match_direct.group(1)
                
                # クエリパラメータからroom_uidを取得
                parsed_url = urlparse(original_url)
                query_params = parse_qs(parsed_url.query)
                room_uid = query_params.get('room_uid', [None])[0]
                
                if not room_uid:
                    return {'error': 'room_uid パラメータが見つかりません'}
                
                # ページにアクセス（リダイレクトの確認のため）
                resp = page.goto(original_url, wait_until='networkidle', timeout=90000)
                if not resp.ok:
                    return {'error': f"ページロードエラー: {resp.status} {resp.status_text}"}
                page.wait_for_load_state("networkidle")
                time.sleep(2)
                
            else:
                return {'error': '対応していないURL形式です'}

            # 3) 予約ページ URL を組み立てて遷移
            reservation_url = (
                f"https://www.spacemarket.com/spaces/{space_id_from_url}"
                f"/rooms/{room_uid}/reservations/new/"
                "?from=room_reservation_button&price_type=HOURLY&promotion_ids=4808&rent_type=1"
            )
            resp2 = page.goto(reservation_url, wait_until='networkidle', timeout=90000)
            if not resp2.ok:
                return {'error': f"予約ページロードエラー: {resp2.status} {resp2.status_text}"}
            page.wait_for_load_state("networkidle")
            time.sleep(3)

            # JSONデータを取得
            json_data = None
            space_id = ''
            plans_data = []
            try:
                script_el = page.query_selector('script#__NEXT_DATA__')
                if script_el:
                    json_str = script_el.inner_text()
                    json_data = json.loads(json_str)
                    # spaceIdを取得（roomFragment.id）
                    room_fragment = json_data.get('props', {}).get('pageProps', {}).get('roomFragment', {})
                    space_id = room_fragment.get('id', '')
                    # プラン情報を取得
                    plans_data = room_fragment.get('plans', {}).get('results', [])
                    
                    # 大きなJSONオブジェクトを即座に削除
                    del json_data
                    
            except Exception as e:
                print(f"JSON取得エラー: {e}")
                space_id = ''

            # スペース名取得
            space_name = ''
            try:
                el = page.query_selector("p.css-4mpmt5")
                if el:
                    space_name = el.inner_text()
            except:
                pass

            # 日付リスト生成
            today = datetime.now(timezone(timedelta(hours=9)))
            dates = [today + timedelta(days=i) for i in range(28)]

            # プラン情報取得 （フォールバック機能付き）
            plans = []
            try:
                # 最大7日先まで試行
                plan_acquired = False
                for fallback_days in range(8):  # 0日後（今日）から7日後まで
                    target_date = today + timedelta(days=fallback_days)
                    date_str = f"{target_date.year}年{target_date.month}月{target_date.day}日"
                    
                    try:
                        # 日付ボタンを探す
                        btn = page.locator(f'button[aria-label="{date_str}"]')
                        
                        # ボタンが見つからない場合は次の月に移動してから再度探す
                        if btn.count() == 0:
                            nxt = page.locator('button[aria-label="次の月"]')
                            if nxt.count() > 0:
                                nxt.click()
                                time.sleep(1)
                                btn = page.locator(f'button[aria-label="{date_str}"]')
                        
                        # ボタンが見つかった場合はクリックしてプラン情報を取得
                        if btn.count() > 0:
                            btn.click()
                            time.sleep(2)
                            
                            # プラン要素を取得
                            elems = page.query_selector_all("li.css-1vwbwmt, li.css-1cpdoqx")
                            if not elems:
                                elems = page.query_selector_all("li button span.css-k6zetj")
                            
                            # プランが見つかった場合は処理
                            if elems:
                                for i, plan in enumerate(elems):
                                    try:
                                        # 価格取得ロジック（優先順位に従って取得）
                                        price = "価格不明"
                                        price_el = plan.query_selector(".css-1y4ezd0")
                                        if price_el:
                                            price = price_el.inner_text()
                                        else:
                                            price_el = plan.query_selector(".css-d362cm")
                                            if price_el:
                                                price = price_el.inner_text()
                                            else:
                                                price_el = plan.query_selector(".css-1sq1blk")
                                                if price_el:
                                                    price = price_el.inner_text()
                                        
                                        # JSONデータからIDと名前を取得
                                        plan_id = ''
                                        plan_name = ''
                                        if i < len(plans_data):
                                            plan_id = plans_data[i].get('id', '')
                                            plan_name = plans_data[i].get('name', '')
                                        plans.append({'name': plan_name, 'price': price, 'id': plan_id})
                                    except:
                                        pass
                                
                                plan_acquired = True
                                print(f"プラン情報を{fallback_days}日後({target_date.month}月{target_date.day}日)のデータから取得しました")
                                break  # プラン取得成功で終了
                                
                    except Exception as e:
                        print(f"{fallback_days}日後のプラン取得試行でエラー: {e}")
                        continue  # 次の日付を試行
                
                if not plan_acquired:
                    print("7日間の試行でもプラン情報を取得できませんでした")
                    
            except Exception as e:
                print(f"プラン情報取得で予期しないエラー: {e}")
                pass

            # 予約状況取得 （既存ロジック）
            all_reserved_times = {}
            for current_date in dates:
                formatted = f"{current_date.month}月{current_date.day}日"
                date_str = f"{current_date.year}年{current_date.month}月{current_date.day}日"
                try:
                    btn = page.locator(f'button[aria-label="{date_str}"]')
                    if btn.count() == 0:
                        # 次の月移動ロジック...
                        nxt = page.locator('button[aria-label="次の月"]')
                        if nxt.count() > 0:
                            nxt.click()
                            time.sleep(1)
                            btn = page.locator(f'button[aria-label="{date_str}"]')
                    if btn.count() == 0:
                        all_reserved_times[formatted] = []
                        continue
                    btn.click()
                    time.sleep(1)
                    slots = page.query_selector_all("div.css-1i0gn25")
                    availability = []
                    zero = datetime.strptime("00:00", "%H:%M")
                    for i, slot in enumerate(slots):
                        t = zero + timedelta(minutes=15 * i)
                        h, m = t.hour, t.minute
                        next_day = h >= 24
                        if next_day: h -= 24
                        ts = f"{h:02d}:{m:02d}"
                        disabled = slot.get_attribute("data-disabled") == "true"
                        selected = slot.get_attribute("data-selected") == "true"
                        status = "不可" if disabled else ("選択中" if selected else "可能")
                        availability.append((ts, status, next_day))
                    # 連続予約抽出
                    rr = []
                    start_idx = None
                    for i, (ts, st, nd) in enumerate(availability):
                        # 予約不可の開始を検出
                        if st == "不可" and (i == 0 or availability[i-1][1] != "不可"):
                            # 開始が24時以降（翌日）の場合はスキップ
                            if nd:
                                start_idx = None  # 明示的にNoneを設定
                                continue
                            start_idx = i
                        
                        # 予約不可の終了を検出して記録
                        if start_idx is not None and (st != "不可" or i == len(availability)-1):
                            end_idx = i if st != "不可" else i+1
                            
                            # 開始時刻と終了時刻の処理
                            st_obj = datetime.strptime(availability[start_idx][0], "%H:%M")
                            en_obj = datetime.strptime(availability[end_idx-1][0], "%H:%M") + timedelta(minutes=15)
                            dur = (end_idx - start_idx) * 15
                            
                            # 終了が翌日にまたがる場合の日付処理
                            end_is_next_day = availability[end_idx-1][2] if end_idx-1 < len(availability) else False
                            
                            rr.append({
                                'start_date': formatted,  # 開始は必ず当日
                                'end_date': formatted if not end_is_next_day else f"{(current_date+timedelta(days=1)).month}月{(current_date+timedelta(days=1)).day}日",
                                'start_time': st_obj.strftime("%H:%M"),
                                'end_time': en_obj.strftime("%H:%M"),
                                'duration_hours': dur // 60,
                                'duration_minutes': dur % 60
                            })
                            start_idx = None
                    all_reserved_times[formatted] = rr
                except:
                    all_reserved_times[formatted] = []

            return {
                'url': original_url,
                'plans': plans,
                'reserved_times': all_reserved_times,
                'timestamp': datetime.now(timezone(timedelta(hours=9))).isoformat(),
                'name': space_name,
                'space_id': space_id
            }

        except Exception as e:
            return {'error': str(e)}
        finally:
            # 確実なクリーンアップ（メルカリコードの方式）
            if page:
                try:
                    page.close()
                except:
                    pass
            if browser:
                try:
                    browser.close()
                except:
                    pass