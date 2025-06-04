import os
import json
import re
import hashlib
import time
from datetime import datetime, timedelta, timezone
import boto3
from playwright.sync_api import sync_playwright
import urllib.request

# DynamoDB テーブル名は環境変数から取得
TABLE_NAME = os.environ.get('TABLE_NAME', 'SpaceRate')

# 祝日データのキャッシュ（Lambda実行中は保持）
_holidays_cache = None
_holidays_cache_time = None
HOLIDAYS_CACHE_DURATION = 3600  # 1時間

def get_japan_holidays():
    """日本の祝日データを取得（キャッシュ付き）"""
    global _holidays_cache, _holidays_cache_time
    
    now = time.time()
    
    # キャッシュが有効な場合はそれを返す
    if _holidays_cache is not None and _holidays_cache_time is not None:
        if now - _holidays_cache_time < HOLIDAYS_CACHE_DURATION:
            return _holidays_cache
    
    try:
        # 祝日APIからデータ取得
        url = "https://holidays-jp.github.io/api/v1/date.json"
        with urllib.request.urlopen(url, timeout=10) as response:
            holidays_data = json.loads(response.read().decode('utf-8'))
            _holidays_cache = holidays_data
            _holidays_cache_time = now
            return holidays_data
    except Exception as e:
        print(f"祝日データ取得エラー: {e}")
        # エラー時は空の辞書を返す（通常の曜日判定にフォールバック）
        return {}

def is_holiday(date_obj):
    """指定された日付が祝日かどうかを判定"""
    holidays = get_japan_holidays()
    date_str = date_obj.strftime('%Y-%m-%d')
    return date_str in holidays

def lambda_handler(event, context):
    # SQSメッセージから URLs パラメータ取得
    all_urls = []
    offset_days = 0  # デフォルトは今日から
    scan_days = 7    # デフォルトは7日間
    
    if 'Records' in event:
        # SQSイベントの場合
        for record in event['Records']:
            try:
                message_body = json.loads(record['body'])
                urls = message_body.get('urls', [])
                offset_days = message_body.get('offset_days', 0)
                scan_days = message_body.get('scan_days', 7)
                if urls and isinstance(urls, list):
                    all_urls.extend(urls)
            except Exception as e:
                print(f"SQSメッセージ解析エラー: {e}")
                continue
    else:
        # 既存のHTTPリクエスト処理（互換性維持）
        if 'body' in event:
            body = json.loads(event['body'] or '{}')
            urls = body.get('urls')
            offset_days = body.get('offset_days', 0)
            scan_days = body.get('scan_days', 7)
        else:
            urls = event.get('urls')
            offset_days = event.get('offset_days', 0)
            scan_days = event.get('scan_days', 7)
        if urls and isinstance(urls, list):
            all_urls = urls
        elif event.get('url'):
            # 単一URL対応（既存の互換性）
            all_urls = [event.get('url')]
    
    if not all_urls:
        return {'statusCode': 400, 'body': json.dumps({'error': 'URL(s) is required'})}

    all_items = []
    errors = []
    
    for url in all_urls:
        try:
            items = scrape_hourly_prices(url, days=scan_days, offset_days=offset_days)
            if items:
                write_items_to_dynamodb(items)
                all_items.extend(items)
        except Exception as e:
            errors.append({
                'url': url,
                'error': str(e)
            })
    
    # 部分的成功でも200を返す
    if all_items:
        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': f'{len(all_items)}件保存完了',
                'successful': len(all_items),
                'failed': len(errors),
                'records': len(all_items),
                'errors': errors,
                'scan_info': {
                    'offset_days': offset_days,
                    'scan_days': scan_days,
                    'start_date': (datetime.now(timezone(timedelta(hours=9))) + timedelta(days=offset_days)).strftime('%Y-%m-%d')
                }
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


def scrape_hourly_prices(original_url, days=7, offset_days=0):
    """
    指定 URL のスペースマーケット予約ページから
    指定日数分の1時間単位プラン価格情報を取得し、
    DynamoDB 格納用のアイテムリストを返す
    """
    items = []
    # JST タイムゾーン
    JST = timezone(timedelta(hours=9))
    now_jst = datetime.now(JST)

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
            user_agent=(
                'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/112.0.0.0 Safari/537.36'
            )
        )
        page = context.new_page()
        
        try:
            # 1) トップページにアクセス（リダイレクト後の URL を取得）
            resp = page.goto(original_url, wait_until='networkidle', timeout=90000)
            if not resp.ok:
                raise Exception(f"ページロードエラー: {resp.status} {resp.status_text}")
            page.wait_for_load_state("networkidle")
            time.sleep(2)

            # 2) spaceId と roomUid を抽出
            redirected = page.url  # e.g. https://www.spacemarket.com/spaces/<spaceId>/?...
            space_match = re.search(r'/spaces/([^/]+)/', redirected)
            room_match = re.search(r'/p/([^/?]+)', original_url)
            if not space_match or not room_match:
                raise Exception('spaceId または roomUid の抽出失敗')
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
                raise Exception(f"予約ページロードエラー: {resp2.status} {resp2.status_text}")
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
                # フォールバック：URLから取得したspaceIdを使用
                space_id = space_id_from_url

            # スペース名を取得
            space_name = ''
            try:
                name_el = page.query_selector('p.css-4mpmt5')
                space_name = name_el.inner_text() if name_el else ''
            except:
                space_name = ''

            # 対象日付リスト
            base = datetime.now(JST) + timedelta(days=offset_days)
            dates = [base + timedelta(days=i) for i in range(days)]
            print(f"処理対象日付 (offset={offset_days}日): {[d.strftime('%Y-%m-%d') for d in dates]}")

            # プラン情報取得（JSONデータから）
            plan_map = {}  # プランindexとデータの対応
            for i, plan_data in enumerate(plans_data):
                plan_map[i] = {
                    'id': plan_data.get('id', ''),
                    'name': plan_data.get('name', '')
                }

            for date_index, current_date in enumerate(dates):
                # 日付ラベル
                date_label = f"{current_date.year}年{current_date.month}月{current_date.day}日"
                iso_date = current_date.strftime('%Y-%m-%d')
                print(f"処理中の日付: {iso_date}")
                # 曜日種別（祝日判定を追加）
                dow = current_date.weekday()
                if dow >= 5 or is_holiday(current_date):  # 土日または祝日
                    day_type = 'weekend'
                else:
                    day_type = 'weekday'

                # 日付選択
                btn = page.locator(f'button[aria-label="{date_label}"]')
                try:
                    # ボタンが見つからない場合は次の月に移動
                    if btn.count() == 0:
                        # 次の月ボタンをクリック
                        next_month_btn = page.locator('button[aria-label="次の月"]')
                        if next_month_btn.count() > 0:
                            next_month_btn.click()
                            time.sleep(1)
                            # 再度日付ボタンを探す
                            btn = page.locator(f'button[aria-label="{date_label}"]')
                    
                    if btn.count() == 0:
                        print(f"日付ボタンが見つかりません: {date_label}")
                        continue
                    
                    btn.click()
                    time.sleep(2)
                except Exception as e:
                    print(f"日付選択エラー: {date_label} - {e}")
                    continue

                # 利用可能時間帯取得
                hours = get_available_hours(page)
                hours.sort()
                
                # 2日目以降は0-11時をスキップ（前日の24-35時として既に処理済み）
                if date_index > 0:
                    hours = [h for h in hours if h >= 12]
                    print(f"  利用可能時間帯 ({iso_date}) ※12時以降のみ処理: {hours}")
                else:
                    print(f"  利用可能時間帯 ({iso_date}): {hours}")

                for hour in hours:
                    # 24時以上は翌日の時間として処理
                    target_date = current_date
                    target_hour = hour
                    
                    if hour >= 24:
                        # 24時以上の場合は翌日の相当する時間に変換
                        target_date = current_date + timedelta(days=1)
                        target_hour = hour - 24
                        # 翌日の曜日種別を再計算（祝日判定を追加）
                        dow = target_date.weekday()
                        if dow >= 5 or is_holiday(target_date):  # 土日または祝日
                            day_type = 'weekend'
                        else:
                            day_type = 'weekday'
                    
                    # 日付をISO形式で生成
                    target_iso_date = target_date.strftime('%Y-%m-%d')
                    
                    # 1時間後
                    start = target_hour
                    end = target_hour + 1
                    # 時刻レンジ設定（元のhourを使用）
                    if not set_time_range(page, hour, 0, hour + 1, 0):
                        continue
                    # プラン取得（価格優先順位付き）
                    plans = get_available_plans_with_priority(page)
                    for idx, plan in enumerate(plans):
                        # JSONデータからplanIdとplanDisplayNameを取得
                        if idx in plan_map:
                            plan_id = plan_map[idx]['id']
                            plan_display_name = plan_map[idx]['name']
                        else:
                            # フォールバック（既存のロジック）
                            plan_display_name = plan['name']
                            plan_id = 'plan_' + hashlib.md5(plan_display_name.encode()).hexdigest()[:8]
                        
                        # price は数値
                        price = plan.get('value') or 0
                        # rate_key
                        dt_start = f"{target_iso_date}T{start:02d}:00"
                        rate_key = f"{dt_start}#{plan_id}"

                        item = {
                            'spaceId': space_id,
                            'rate_key': rate_key,
                            'datetime': dt_start,
                            'name': space_name,
                            'url': original_url,
                            'planId': plan_id,
                            'planDisplayName': plan_display_name,
                            'price': price,
                            'day_type': day_type,
                            'created_at': now_jst.isoformat(),
                            'scan_date': now_jst.strftime('%Y-%m-%d'),  # スキャン実行日
                            'forecast_days': offset_days  # 何日先のデータか
                        }
                        items.append(item)
            
            print(f"スクレイピング完了 ({original_url}): {len(items)}件のデータを取得")

        except Exception as e:
            print(f"スクレイピングエラー ({original_url}): {e}")
            raise e
        finally:
            browser.close()
    
    return items


def write_items_to_dynamodb(items):
    """DynamoDB へ複数アイテムを個別に put"""
    dynamo = boto3.resource('dynamodb')
    table = dynamo.Table(TABLE_NAME)
    for item in items:
        table.put_item(Item=item)


def get_available_hours(page):
    """開始時刻ドロップダウンから有効な時間（整数）を取得"""
    try:
        opts = page.locator('select[aria-label="開始時"]').evaluate(
            '(el) => Array.from(el.options).map(o=>({v:parseInt(o.value), d:o.disabled}))'
        )
        return [o['v'] for o in opts if not o['d']]
    except:
        return []


def set_time_range(page, sh, sm, eh, em):
    """開始/終了の時刻を選択して料金更新を待機"""
    try:
        page.locator('select[aria-label="開始時"]').select_option(value=str(sh))
        page.locator('select[aria-label="開始分"]').select_option(value=f"{sm:02d}")
        page.locator('select[aria-label="終了時"]').select_option(value=str(eh))
        page.locator('select[aria-label="終了分"]').select_option(value=f"{em:02d}")
        time.sleep(1.5)
        return True
    except:
        return False


def get_available_plans_with_priority(page):
    """プラン要素から名前と価格を抽出（価格の優先順位付き）"""
    plans = []
    els = page.query_selector_all('ul.css-n9qrp8 > li')
    for el in els:
        try:
            # プラン名
            n_el = el.query_selector('span.css-k6zetj')
            name = n_el.inner_text() if n_el else el.inner_text()
            
            # 価格取得（優先順位に従って取得）
            price = "0"
            price_el = el.query_selector(".css-1y4ezd0")
            if price_el:
                price = price_el.inner_text()
            else:
                price_el = el.query_selector(".css-d362cm")
                if price_el:
                    price = price_el.inner_text()
                else:
                    price_el = el.query_selector(".css-1sq1blk")
                    if price_el:
                        price = price_el.inner_text()
            
            # 価格を数値に変換
            val = int(''.join(filter(str.isdigit, price))) if price else 0
            plans.append({'name': name, 'value': val})
        except:
            continue
    return plans
