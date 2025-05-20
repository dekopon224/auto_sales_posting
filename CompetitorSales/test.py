from playwright.sync_api import sync_playwright
import time
from datetime import datetime, timedelta

def main():
    # Playwrightを初期化
    with sync_playwright() as p:
        # ブラウザを起動（headless=Falseで画面表示モード）
        browser = p.chromium.launch(headless=False)
        
        # 新しいページを開く
        page = browser.new_page()
        
        # URLにアクセス
        page.goto("https://www.spacemarket.com/spaces/dcfsa_rj0ojpnpdk/rooms/f4l-ByT2WMODjjNB/reservations/new/?from=room_reservation_button&price_type=HOURLY&rent_type=1")
        
        # ページの読み込みを待機
        page.wait_for_load_state("networkidle")
        time.sleep(3)
        
        # 2週間分の日付を生成
        today = datetime.now()
        dates = [today + timedelta(days=i) for i in range(14)]
        
        # 最初の日付をクリックして、プラン情報とスロットを表示させる
        first_date = dates[0]
        date_str = f"{first_date.year}年{first_date.month}月{first_date.day}日"
        formatted_date = f"{first_date.month}月{first_date.day}日"
        
        try:
            # 該当する日付ボタンを探してクリック
            date_button = page.locator(f'button[aria-label="{date_str}"]')
            date_button.click()
            print(f"{formatted_date}を選択しました")
            
            # プランが表示されるまで待機
            time.sleep(3)
            
            # プラン情報を取得して表示
            plan_elements = page.query_selector_all("li.css-1vwbwmt, li.css-1cpdoqx")
            
            print("\n===== プラン一覧 =====")
            print(f"プラン数: {len(plan_elements)}")
            
            if len(plan_elements) == 0:
                # プランが見つからない場合、より一般的なセレクタで試みる
                plan_elements = page.query_selector_all("li button span.css-k6zetj")
                print(f"代替セレクタでのプラン数: {len(plan_elements)}")
            
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
                    
                    print(f"プラン名: {plan_name}")
                    print(f"価格: {price}")
                    print("-" * 30)
                except Exception as e:
                    print(f"プラン情報の取得中にエラーが発生しました: {e}")
                    # HTMLの構造をデバッグ
                    try:
                        print(f"プラン要素HTML: {plan.inner_html()}")
                    except:
                        print("プラン要素のHTMLを取得できませんでした")
        except Exception as e:
            print(f"初回日付選択でエラーが発生しました: {e}")
        
        # 全期間の予約情報を格納する辞書
        all_reserved_times = {}
        
        # 各日付の予約状況を取得
        print("\n===== 2週間分の予約状況 =====")
        
        for current_date in dates:
            date_str = f"{current_date.year}年{current_date.month}月{current_date.day}日"
            formatted_date = f"{current_date.month}月{current_date.day}日"
            
            print(f"\n{formatted_date}の予約状況を確認中...")
            
            try:
                # 該当する日付ボタンを探す
                date_button = page.locator(f'button[aria-label="{date_str}"]')
                
                # 日付ボタンが見つからない場合は次の月に移動
                if date_button.count() == 0:
                    print(f"{formatted_date}のボタンが見つかりません。次の月に移動します...")
                    next_month_button = page.locator('button[aria-label="次の月"]')
                    next_month_button.click()
                    time.sleep(2)  # 月の切り替えを待機
                    
                    # 日付ボタンを再度探す
                    date_button = page.locator(f'button[aria-label="{date_str}"]')
                
                # 日付ボタンをクリック
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
        
        # 全期間の予約状況を表示
        print("\n===== 2週間分の予約済み時間帯 =====")
        
        has_reservations = False
        for date, reserved_ranges in all_reserved_times.items():
            if reserved_ranges:
                has_reservations = True
                print(f"\n【{date}】")
                for time_range in reserved_ranges:
                    duration_str = ""
                    if time_range['duration_hours'] > 0:
                        duration_str += f"{time_range['duration_hours']}時間"
                    if time_range['duration_minutes'] > 0:
                        duration_str += f"{time_range['duration_minutes']}分"
                    
                    print(f"・{time_range['start_date']} {time_range['start_time']}から{time_range['end_date']} {time_range['end_time']}　{duration_str}")
        
        if not has_reservations:
            print("2週間分の予約はありません")
        
        # ユーザーが確認できるよう、キー入力があるまで待機
        print("\nブラウザが表示されています。終了するには何かキーを押してください...")
        input()
        
        # ブラウザを閉じる
        browser.close()

if __name__ == "__main__":
    main()