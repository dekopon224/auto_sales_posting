import boto3
import json
from datetime import datetime, timedelta, timezone
import time
from playwright.sync_api import sync_playwright

def lambda_handler(event, context):
    # APIリクエストからURLを取得
    if 'body' in event:
        try:
            body = json.loads(event['body'])
            url = body.get('url')
        except:
            return {
                'statusCode': 400,
                'body': json.dumps({
                    'error': 'Invalid request body'
                })
            }
    else:
        # テスト時などの直接呼び出し
        url = event.get('url')
    
    # URLが指定されていない場合はエラー
    if not url:
        return {
            'statusCode': 400,
            'body': json.dumps({
                'error': 'URL parameter is required'
            })
        }

    try:
        # Playwrightを使用して予約情報とプラン情報を取得
        reservation_data = get_reservation_data(url)
        
        # JSTで現在時刻を取得
        JST = timezone(timedelta(hours=9))
        now = datetime.now(JST)
        
        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': f"データを {now.strftime('%Y-%m-%d %H:%M:%S')} に取得しました。",
                'data': reservation_data
            }, ensure_ascii=False)
        }

    except Exception as e:
        import traceback
        return {
            'statusCode': 500,
            'body': json.dumps({
                'error': f"エラーが発生しました: {str(e)}",
                'traceback': traceback.format_exc()
            }, ensure_ascii=False)
        }

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
                'timestamp': datetime.now(timezone(timedelta(hours=9))).isoformat()
            }
            
            return result
            
        except Exception as e:
            print(f"スクレイピング中にエラーが発生しました: {str(e)}")
            import traceback
            print(traceback.format_exc())
            return {'error': str(e), 'traceback': traceback.format_exc()}
        finally:
            browser.close()