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
    # URL パラメータ取得
    if 'body' in event:
        body = json.loads(event['body'] or '{}')
        url = body.get('url')
    else:
        url = event.get('url')
    if not url:
        return { 'statusCode': 400, 'body': json.dumps({'error': 'URL is required'}) }

    # スクレイピング
    reservation_data = get_reservation_data(url)
    if 'error' in reservation_data:
        return { 'statusCode': 500, 'body': json.dumps(reservation_data, ensure_ascii=False) }

    # DynamoDB へ保存
    try:
        write_to_dynamodb(url, reservation_data)
    except Exception as e:
        return {
            'statusCode': 500,
            'body': json.dumps({'error': f"DynamoDB書き込み失敗: {e}"}, ensure_ascii=False)
        }

    return {
        'statusCode': 200,
        'body': json.dumps({'message': '保存完了', 'records': reservation_data}, ensure_ascii=False)
    }


def write_to_dynamodb(url, data):
    """
    reservation_data の構造
      {
        'url': ...,
        'plans': [ {'name': planDisplayName, 'price': priceStr}, ... ],
        'reserved_times': {
           '5月17日': [ {'start_time':'10:00','end_time':'11:00',…}, … ],
           …
        },
        'timestamp': '2025-05-16T08:00:00+09:00'
      }
    を展開して、CompetitorSales テーブルへ put_item します。
    """
    # DynamoDB Table
    dynamo = boto3.resource('dynamodb')
    table = dynamo.Table(TABLE_NAME)

    # URLからroomIdを抽出
    room_id_match = re.search(r'/rooms/([^/]+)', url)
    if room_id_match:
        space_id = room_id_match.group(1)
    else:
        # 抽出できない場合はURLからハッシュを生成
        space_id = "unknown_" + hashlib.md5(url.encode('utf-8')).hexdigest()[:10]

    # 今の JST 年
    JST = timezone(timedelta(hours=9))
    now_jst = datetime.now(JST)

    for plan in data['plans']:
        disp_name = plan['name']
        # 数字だけ抜き出して int に (「¥1,000」→1000)
        price = int(re.sub(r'\D', '', plan['price'])) if plan['price'] else 0

        # planId を MD5 で固定生成
        plan_id = 'plan_' + hashlib.md5(disp_name.encode('utf-8')).hexdigest()[:8]

        # 各日付の予約帯を展開
        for formatted_date, ranges in data['reserved_times'].items():
            # "5月17日" → (month, day)
            m, d = map(int, re.match(r'(\d+)月(\d+)日', formatted_date).groups())
            year = now_jst.year
            reservation_date = f"{year}-{m:02d}-{d:02d}"

            for slot in ranges:
                sk = f"{plan_id}#{reservation_date}#{slot['start_time']}"

                # 修正：利用時間を計算
                start_hour, start_minute = map(int, slot['start_time'].split(':'))
                end_hour, end_minute = map(int, slot['end_time'].split(':'))
                
                # 修正：翌日に跨る場合の対応
                if end_hour < start_hour:
                    end_hour += 24
                    
                start_minutes = start_hour * 60 + start_minute
                end_minutes = end_hour * 60 + end_minute
                usage_hours = (end_minutes - start_minutes) / 60  # 時間単位の利用時間
                
                # 修正：利用時間に基づいて価格を計算
                total_price = int(price * usage_hours)

                item = {
                    'spaceId':       space_id,
                    'sortKey':       sk,
                    'planId':        plan_id,
                    'planDisplayName': disp_name,
                    'reservationDate': reservation_date,
                    'start_time':    slot['start_time'],
                    'end_time':      slot['end_time'],
                    'price':         total_price,  # 修正：単価ではなく総額
                    'created_at':    now_jst.isoformat(),
                    'url':           url,          # 修正：URLを追加
                    'name':          data.get('name', '')  # 修正：施設名を追加
                }
                # 必要に応じて他属性（name, url, holiday…）もここに追加

                # DynamoDB に書き込み
                table.put_item(Item=item)

def get_reservation_data(url):
    """Playwrightを使用して予約情報とプラン情報を取得する関数"""
    
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
            # URLにアクセス
            response = page.goto(url, wait_until='networkidle', timeout=90000)
            
            if not response.ok:
                print(f"ページロードエラー: {response.status} {response.status_text}")
                return {
                    'error': f"ページロードエラー: {response.status} {response.status_text}"
                }
            
            # ページの読み込みを待機
            page.wait_for_load_state("networkidle")
            time.sleep(3)
            
            # 修正：スペース名を取得
            space_name = None
            try:
                space_name_element = page.query_selector("p.css-4mpmt5")
                if space_name_element:
                    space_name = space_name_element.inner_text()
            except Exception as e:
                print(f"スペース名の取得中にエラーが発生しました: {e}")
            
            # 2週間分の日付を生成
            today = datetime.now(timezone(timedelta(hours=9)))  # JST
            dates = [today + timedelta(days=i) for i in range(14)]
            
            # 最初の日付をクリックしてプラン情報を取得
            first_date = dates[0]
            date_str = f"{first_date.year}年{first_date.month}月{first_date.day}日"
            formatted_date = f"{first_date.month}月{first_date.day}日"
            
            # プラン情報
            plans = []
            
            try:
                # 該当する日付ボタンを探してクリック
                date_button = page.locator(f'button[aria-label="{date_str}"]')
                date_button.click()
                
                # プランが表示されるまで待機
                time.sleep(3)
                
                # プラン情報を取得
                plan_elements = page.query_selector_all("li.css-1vwbwmt, li.css-1cpdoqx")
                
                if len(plan_elements) == 0:
                    # プランが見つからない場合、より一般的なセレクタで試みる
                    plan_elements = page.query_selector_all("li button span.css-k6zetj")
                
                for plan in plan_elements:
                    try:
                        # プラン名を取得
                        plan_name_element = plan.query_selector(".css-k6zetj")
                        if not plan_name_element:
                            # ボタン自体がプラン要素の場合
                            plan_name = plan.inner_text()
                        else:
                            plan_name = plan_name_element.inner_text()
                        
                        # 価格を取得（定価を優先）
                        price_element = plan.query_selector(".css-1y4ezd0, .css-1sq1blk, .css-d362cm")
                        price = price_element.inner_text() if price_element else "価格不明"
                        
                        plans.append({
                            'name': plan_name,
                            'price': price
                        })
                    except Exception as e:
                        print(f"プラン情報の取得中にエラーが発生しました: {e}")
            except Exception as e:
                print(f"初回日付選択でエラーが発生しました: {e}")
            
            # 全期間の予約情報を格納する辞書
            all_reserved_times = {}
            
            # 各日付の予約状況を取得
            for current_date in dates:
                date_str = f"{current_date.year}年{current_date.month}月{current_date.day}日"
                formatted_date = f"{current_date.month}月{current_date.day}日"
                
                try:
                    # 該当する日付ボタンを探してクリック
                    date_button = page.locator(f'button[aria-label="{date_str}"]')
                    date_button.click()
                    
                    # 日付選択後の更新を待つ
                    time.sleep(2)
                    
                    # 予約状況の取得
                    time_slots = page.query_selector_all("div.css-1i0gn25")
                    
                    # 予約状況を整理
                    availability = []
                    start_time = datetime.strptime("00:00", "%H:%M")
                    
                    for i, slot in enumerate(time_slots):
                        # 時間計算
                        current_time = start_time + timedelta(minutes=15 * i)
                        hour = current_time.hour
                        minute = current_time.minute
                        
                        # 翌日の時間表示を調整
                        is_next_day = hour >= 24
                        if is_next_day:
                            hour -= 24
                        
                        time_str = f"{hour:02d}:{minute:02d}"
                        
                        # 予約状態を確認
                        is_disabled = slot.get_attribute("data-disabled") == "true"
                        is_selected = slot.get_attribute("data-selected") == "true"
                        
                        status = "不可" if is_disabled else ("選択中" if is_selected else "可能")
                        
                        availability.append((time_str, status, is_next_day))
                    
                    # 連続した予約済み時間を探す
                    reserved_ranges = []
                    start_idx = None
                    
                    for i, (time_str, status, is_next_day) in enumerate(availability):
                        if status == "不可" and (i == 0 or availability[i-1][1] != "不可"):
                            start_idx = i
                        elif (status != "不可" or i == len(availability) - 1) and i > 0 and start_idx is not None:
                            if status == "不可" and i == len(availability) - 1:
                                i += 1  # 最後のスロットが予約不可な場合
                            
                            # 開始時間
                            start_time_obj = datetime.strptime(availability[start_idx][0], "%H:%M")
                            end_time_obj = datetime.strptime(availability[i-1][0], "%H:%M") + timedelta(minutes=15)
                            
                            # 時間の長さを計算（分単位）
                            duration_minutes = (i - start_idx) * 15
                            hours = duration_minutes // 60
                            minutes = duration_minutes % 60
                            
                            # 日付を設定
                            next_date = current_date + timedelta(days=1)
                            start_date = formatted_date if not availability[start_idx][2] else f"{next_date.month}月{next_date.day}日"
                            end_date = formatted_date if not availability[i-1][2] else f"{next_date.month}月{next_date.day}日"
                            
                            # 時間帯情報を追加
                            reserved_ranges.append({
                                'start_date': start_date,
                                'end_date': end_date,
                                'start_time': start_time_obj.strftime("%H:%M"),
                                'end_time': end_time_obj.strftime("%H:%M"),
                                'duration_hours': hours,
                                'duration_minutes': minutes
                            })
                            
                            start_idx = None
                    
                    # 予約された時間帯を保存
                    all_reserved_times[formatted_date] = reserved_ranges
                    
                except Exception as e:
                    print(f"エラー: {formatted_date}の予約状況取得に失敗しました: {e}")
                    all_reserved_times[formatted_date] = []
            
            # 取得結果をまとめる
            result = {
                'url': url,
                'plans': plans,
                'reserved_times': all_reserved_times,
                'timestamp': datetime.now(timezone(timedelta(hours=9))).isoformat(),
                'name': space_name  # 修正：施設名を追加
            }
            
            return result
            
        except Exception as e:
            print(f"スクレイピング中にエラーが発生しました: {str(e)}")
            import traceback
            print(traceback.format_exc())
            return {'error': str(e), 'traceback': traceback.format_exc()}
        finally:
            browser.close()