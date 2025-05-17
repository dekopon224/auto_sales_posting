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
        
        # 少し待機
        time.sleep(2)
        
        # 今日の日付（2025年5月17日）のボタンをクリック
        selected_date = "2025年5月17日"
        try:
            date_button = page.locator('button[aria-label="2025年5月17日"]')
            date_button.click()
            print(f"日付を選択しました: {selected_date}")
        except Exception as e:
            print(f"日付ボタンのクリックに失敗しました: {e}")
            # 別の方法で日付を選択する
            try:
                date_button = page.locator('button[aria-current="date"]')
                date_button.click()
                print("現在日の日付ボタンをクリックしました")
                # 現在の日付を取得
                current_date = datetime.now()
                selected_date = f"{current_date.year}年{current_date.month}月{current_date.day}日"
            except:
                print("日付の選択に失敗しました。手動で選択してください。")
        
        # 日付選択後の更新を待つ
        time.sleep(3)
        
        # プラン情報を取得して表示
        plan_elements = page.query_selector_all("li.css-1vwbwmt, li.css-1cpdoqx")
        
        print("\n===== プラン一覧 =====")
        for plan in plan_elements:
            # プラン名を取得
            plan_name = plan.query_selector(".css-k6zetj").inner_text()
            
            # 価格を取得（定価を優先）
            price_element = plan.query_selector(".css-1y4ezd0")
            if not price_element:
                price_element = plan.query_selector(".css-1sq1blk")
            
            price = price_element.inner_text() if price_element else "価格不明"
            
            print(f"プラン名: {plan_name}")
            print(f"価格: {price}")
            print("-" * 30)
        
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
        
        # 予約されている時間帯をまとめる
        print("\n===== 予約されている時間 =====")
        
        # 選択した日付から月と日を抽出
        month, day = None, None
        try:
            date_parts = selected_date.split('年')[1].split('月')
            month = int(date_parts[0])
            day = int(date_parts[1].replace('日', ''))
        except:
            # 日付の解析に失敗した場合は現在の日付を使用
            now = datetime.now()
            month = now.month
            day = now.day
        
        # 翌日の日付を計算
        next_day_date = datetime(2025, month, day) + timedelta(days=1)
        next_month = next_day_date.month
        next_day = next_day_date.day
        
        reserved_ranges = []
        start_idx = None
        
        # 連続した予約済み時間を探す
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
                start_date = f"{month}月{day}日" if not availability[start_idx][2] else f"{next_month}月{next_day}日"
                end_date = f"{month}月{day}日" if not availability[i-1][2] else f"{next_month}月{next_day}日"
                
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
        
        # 予約済みの時間帯を表示
        if reserved_ranges:
            for i, time_range in enumerate(reserved_ranges):
                duration_str = ""
                if time_range['duration_hours'] > 0:
                    duration_str += f"{time_range['duration_hours']}時間"
                if time_range['duration_minutes'] > 0:
                    duration_str += f"{time_range['duration_minutes']}分"
                
                print(f"・{time_range['start_date']} {time_range['start_time']}から{time_range['end_date']} {time_range['end_time']}　{duration_str}")
        else:
            print("予約されている時間帯はありません")
        
        # ユーザーが確認できるよう、キー入力があるまで待機
        print("\nブラウザが表示されています。終了するには何かキーを押してください...")
        input()
        
        # ブラウザを閉じる
        browser.close()

if __name__ == "__main__":
    main()