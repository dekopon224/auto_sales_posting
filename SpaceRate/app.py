import os
import json
import re
import hashlib
import time
from datetime import datetime, timedelta, timezone
import boto3
from playwright.sync_api import sync_playwright

# DynamoDB テーブル名は環境変数から取得
TABLE_NAME = os.environ.get('TABLE_NAME', 'SpaceRate')

def lambda_handler(event, context):
    # リクエストから URL を取得
    payload = json.loads(event.get('body', '{}'))
    url = payload.get('url') or event.get('url')
    if not url:
        return {'statusCode': 400, 'body': json.dumps({'error': 'URL is required'})}

    try:
        items = scrape_hourly_prices(url)
        write_items_to_dynamodb(items)
        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': '保存完了',
                'records': len(items)
            }, ensure_ascii=False)
        }
    except Exception as e:
        return {'statusCode': 500, 'body': json.dumps({'error': str(e)})}


def scrape_hourly_prices(url, days=7):
    """
    指定 URL のスペースマーケット予約ページから
    指定日数分の1時間単位プラン価格情報を取得し、
    DynamoDB 格納用のアイテムリストを返す
    """
    items = []
    # JST タイムゾーン
    JST = timezone(timedelta(hours=9))
    now_jst = datetime.now(JST)

    # roomId (spaceId) を URL から抽出
    m = re.search(r'/rooms/([^/]+)', url)
    space_id = m.group(1) if m else 'unknown_' + hashlib.md5(url.encode()).hexdigest()[:8]

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
        page.goto(url, wait_until='networkidle', timeout=90000)
        time.sleep(3)

        # スペース名を取得
        try:
            name_el = page.query_selector('p.css-4mpmt5')
            space_name = name_el.inner_text() if name_el else ''
        except:
            space_name = ''

        # 対象日付リスト
        base = datetime.now(JST)
        dates = [base + timedelta(days=i) for i in range(days)]

        for current_date in dates:
            # 日付ラベル
            date_label = f"{current_date.year}年{current_date.month}月{current_date.day}日"
            iso_date = current_date.strftime('%Y-%m-%d')
            # 曜日種別
            dow = current_date.weekday()
            day_type = 'weekday' if dow < 5 else 'weekend'

            # 日付選択
            btn = page.locator(f'button[aria-label="{date_label}"]')
            try:
                btn.click()
                time.sleep(2)
            except:
                continue

            # 利用可能時間帯取得
            hours = get_available_hours(page)
            hours.sort()

            for hour in hours:
                # 24時以上は翌日の時間として処理
                target_date = current_date
                target_hour = hour
                
                if hour >= 24:
                    # 24時以上の場合は翌日の相当する時間に変換
                    target_date = current_date + timedelta(days=1)
                    target_hour = hour - 24
                    # 翌日の曜日種別を再計算
                    dow = target_date.weekday()
                    day_type = 'weekday' if dow < 5 else 'weekend'
                
                # 日付をISO形式で生成
                target_iso_date = target_date.strftime('%Y-%m-%d')
                
                # 1時間後
                start = target_hour
                end = target_hour + 1
                # 時刻レンジ設定（元のhourを使用）
                if not set_time_range(page, hour, 0, hour + 1, 0):
                    continue
                # プラン取得
                plans = get_available_plans(page)
                for plan in plans:
                    name = plan['name']
                    # price は数値
                    price = plan.get('value') or 0
                    # planId 固定生成
                    pid = 'plan_' + hashlib.md5(name.encode()).hexdigest()[:8]
                    # rate_key
                    dt_start = f"{target_iso_date}T{start:02d}:00"
                    rate_key = f"{dt_start}#{pid}"

                    item = {
                        'spaceId': space_id,
                        'rate_key': rate_key,
                        'datetime': dt_start,
                        'name': space_name,
                        'url': url,
                        'planId': pid,
                        'planDisplayName': name,
                        'price': price,
                        'day_type': day_type,
                        'created_at': now_jst.isoformat()
                    }
                    items.append(item)

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


def get_available_plans(page):
    """プラン要素から名前と価格を抽出"""
    plans = []
    els = page.query_selector_all('ul.css-n9qrp8 > li')
    for el in els:
        try:
            # プラン名
            n_el = el.query_selector('span.css-k6zetj')
            name = n_el.inner_text() if n_el else el.inner_text()
            # 価格取得
            p_el = el.query_selector('span.css-1sq1blk, span.css-d362cm, span.css-1y4ezd0')
            text = p_el.inner_text() if p_el else ''
            val = int(''.join(filter(str.isdigit, text))) if text else 0
            plans.append({'name': name, 'value': val})
        except:
            continue
    return plans
