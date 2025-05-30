import boto3
import json
import re
import hashlib
from datetime import datetime, timedelta, timezone
import time
from playwright.sync_api import sync_playwright

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

    # URLからroomIdを抽出
    room_match = re.search(r'/p/([^/?]+)', url)
    room_uid = room_match.group(1) if room_match else None

    # spaceId はJSONから取得したものを使用
    space_id = data.get('space_id', 'unknown')

    JST = timezone(timedelta(hours=9))
    now_jst = datetime.now(JST)

    for plan in data['plans']:
        disp_name = plan['name']
        price = int(re.sub(r'\D', '', plan['price'])) if plan['price'] else 0
        plan_id = plan.get('id', '')

        for formatted_date, ranges in data['reserved_times'].items():
            m, d = map(int, re.match(r'(\d+)月(\d+)日', formatted_date).groups())
            year = now_jst.year
            reservation_date = f"{year}-{m:02d}-{d:02d}"

            for slot in ranges:
                sk = f"{plan_id}#{reservation_date}#{slot['start_time']}"

                start_hour, start_minute = map(int, slot['start_time'].split(':'))
                end_hour, end_minute = map(int, slot['end_time'].split(':'))
                if end_hour < start_hour:
                    end_hour += 24
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
                    'name':            data.get('name', '')
                }
                table.put_item(Item=item)


def get_reservation_data(original_url):
    """Playwrightを使用して、トップページ→予約ページと遷移後に予約情報とプラン情報を取得する関数"""
    with sync_playwright() as p:
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
        context = browser.new_context(
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/112.0.0.0 Safari/537.36'
        )
        page = context.new_page()

        try:
            # 1) トップページにアクセス（リダイレクト後の URL を取得）
            resp = page.goto(original_url, wait_until='networkidle', timeout=90000)
            if not resp.ok:
                return {'error': f"ページロードエラー: {resp.status} {resp.status_text}"}
            page.wait_for_load_state("networkidle")
            time.sleep(2)

            # 2) spaceId と roomUid を抽出
            redirected = page.url  # e.g. https://www.spacemarket.com/spaces/<spaceId>/?...
            space_match = re.search(r'/spaces/([^/]+)/', redirected)
            room_match = re.search(r'/p/([^/?]+)', original_url)
            if not space_match or not room_match:
                return {'error': 'spaceId または roomUid の抽出失敗'}
            space_id_from_url = space_match.group(1)
            room_uid = room_match.group(1)

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
            dates = [today + timedelta(days=i) for i in range(14)]

            # プラン情報取得 （既存ロジック）
            plans = []
            try:
                date_str = f"{today.year}年{today.month}月{today.day}日"
                page.locator(f'button[aria-label="{date_str}"]').click()
                time.sleep(2)
                elems = page.query_selector_all("li.css-1vwbwmt, li.css-1cpdoqx")
                if not elems:
                    elems = page.query_selector_all("li button span.css-k6zetj")
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
            except:
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
                        if st == "不可" and (i == 0 or availability[i-1][1] != "不可"):
                            start_idx = i
                        if start_idx is not None and (st != "不可" or i == len(availability)-1):
                            end_idx = i if st != "不可" else i+1
                            st_obj = datetime.strptime(availability[start_idx][0], "%H:%M")
                            en_obj = datetime.strptime(availability[end_idx-1][0], "%H:%M") + timedelta(minutes=15)
                            dur = (end_idx - start_idx) * 15
                            rr.append({
                                'start_date': formatted if not availability[start_idx][2] else f"{(current_date+timedelta(days=1)).month}月{(current_date+timedelta(days=1)).day}日",
                                'end_date':   formatted if not availability[end_idx-1][2] else f"{(current_date+timedelta(days=1)).month}月{(current_date+timedelta(days=1)).day}日",
                                'start_time': st_obj.strftime("%H:%M"),
                                'end_time':   en_obj.strftime("%H:%M"),
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
            browser.close()
