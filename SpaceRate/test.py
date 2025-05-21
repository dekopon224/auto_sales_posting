from playwright.sync_api import sync_playwright
import time
from datetime import datetime, timedelta
import pandas as pd

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
        
        # 1週間分の日付を生成
        today = datetime.now()
        dates = [today + timedelta(days=i) for i in range(7)]
        
        # すべてのプラン情報を格納する辞書（キー: プラン名）
        all_plans_dict = {}
        
        # 結果を格納するための辞書
        all_price_data = {}
        
        # 各日付ごとに処理
        for i, current_date in enumerate(dates):
            date_str = f"{current_date.year}年{current_date.month}月{current_date.day}日"
            formatted_date = f"{current_date.month}月{current_date.day}日"
            
            print(f"\n===== {formatted_date}の料金情報 =====")
            
            # 日付ボタンをクリック
            try:
                date_button = page.locator(f'button[aria-label="{date_str}"]')
                date_button.click()
                time.sleep(2)
            except Exception as e:
                print(f"日付選択でエラーが発生しました: {e}")
                continue
            
            # この日付の料金情報を格納する辞書
            daily_price_data = {}
            
            # 利用可能な時間帯を取得
            available_hours = get_available_hours(page)
            if not available_hours:
                print(f"  {formatted_date}の利用可能な時間が見つかりませんでした")
                continue
            
            # 初日以降は12時以降の時間帯のみ処理する
            if i > 0:  # 初日(i=0)以外の場合
                available_hours = [hour for hour in available_hours if hour >= 12]
                print(f"  12時以降に絞り込み: {len(available_hours)}個")
            else:
                print(f"  利用可能な時間: {len(available_hours)}個")
            
            # 利用可能な時間ごとに1時間枠を処理
            for start_hour in available_hours:
                # 終了時間は開始時間+1時間
                end_hour = (start_hour + 1) % 24  # 24時→0時、25時→1時に変換
                
                # 時間文字列を作成（24時以降は0時以降として表示）
                display_start_hour = start_hour
                if display_start_hour >= 24:
                    display_start_hour -= 24
                
                display_end_hour = end_hour
                # 日を跨ぐ場合（23時→0時など）は、表示上は24時として扱う
                if start_hour == 23 and end_hour == 0:
                    display_end_hour = 24
                # 24時以降の場合も修正
                elif display_start_hour >= 0 and display_start_hour <= 5 and end_hour == display_start_hour + 1:
                    # 00:00-01:00, 01:00-02:00 などの通常の1時間枠
                    display_end_hour = end_hour
                
                start_time = f"{display_start_hour:02d}:00"
                end_time = f"{display_end_hour:02d}:00"
                
                print(f"\n時間帯: {start_time} - {end_time}")
                # デバッグ情報を出力
                print(f"  内部時間値: start_hour={start_hour}, end_hour={end_hour}, " +
                      f"display_start_hour={display_start_hour}, display_end_hour={display_end_hour}")
                
                # 日付選択が残っているか確認し、残っていなければ再選択
                try:
                    date_is_selected = page.locator(f'button[aria-label="{date_str}"][aria-selected="true"]').count() > 0
                    if not date_is_selected:
                        print("  日付選択が解除されたため、再選択します")
                        date_button = page.locator(f'button[aria-label="{date_str}"]')
                        date_button.click()
                        time.sleep(2)
                except Exception:
                    # エラーが発生した場合も日付を再選択
                    print("  日付選択状態を確認できないため、再選択します")
                    date_button = page.locator(f'button[aria-label="{date_str}"]')
                    date_button.click()
                    time.sleep(2)
                
                # 開始・終了時間を設定
                if not set_time_range(page, start_hour, 0, start_hour + 1, 0):
                    print(f"  時間設定に失敗しました: {start_time} - {end_time}")
                    continue
                
                # 予約状況を確認
                if is_time_slot_reserved(page, start_hour):
                    print(f"  この時間帯は予約済みのため、スキップします: {start_time} - {end_time}")
                    continue
                
                # 選択した時間枠のプラン情報を取得（その日・その時間帯で利用可能なプラン）
                date_time_plans = get_available_plans(page, f"{formatted_date} {start_time}-{end_time}")
                
                # 新しいプランを全体のプラン辞書に追加
                for plan in date_time_plans:
                    if plan['name'] not in all_plans_dict:
                        all_plans_dict[plan['name']] = plan
                
                # この時間枠のプランごとの料金を取得
                time_slot_prices = get_prices_for_plans(page, date_time_plans)
                
                # 結果を保存
                if time_slot_prices:
                    daily_price_data[f"{start_time}-{end_time}"] = time_slot_prices
            
            # 日付ごとの結果を保存
            all_price_data[formatted_date] = daily_price_data
        
        # 結果を表形式で表示
        print_price_table(all_price_data)
        
        # 結果をCSVに保存（全プランを含める）
        save_to_csv(all_price_data, list(all_plans_dict.keys()))
        
        # ユーザーが確認できるよう、キー入力があるまで待機
        print("\nブラウザが表示されています。終了するには何かキーを押してください...")
        input()
        
        # ブラウザを閉じる
        browser.close()

def get_available_hours(page):
    """利用可能な時間のリストを取得する"""
    available_hours = []
    
    try:
        # 開始時間のプルダウンから利用可能な時間を取得
        start_hour_select = page.locator('select[aria-label="開始時"]')
        start_hour_options = start_hour_select.evaluate("""(element) => {
            return Array.from(element.options).map(option => {
                return {
                    value: parseInt(option.value),
                    text: option.text,
                    disabled: option.disabled
                };
            });
        }""")
        
        print(f"  開始時間オプション数: {len(start_hour_options)}")
        
        # 各時間を処理
        for option in start_hour_options:
            if not option['disabled']:
                available_hours.append(option['value'])
        
        # ソート（念のため）
        available_hours.sort()
        
        print(f"  利用可能な時間: {len(available_hours)}個")
        
    except Exception as e:
        print(f"  利用可能な時間の取得中にエラーが発生しました: {e}")
    
    return available_hours

def is_time_slot_reserved(page, start_hour):
    """指定された時間枠が予約済みかどうかを確認する"""
    try:
        time_slots = page.query_selector_all("div.css-1i0gn25")
        
        # 1時間の範囲をチェック（15分単位で4つ）
        start_index = start_hour * 4  # 15分刻みなので1時間=4スロット
        end_index = start_index + 3  # 1時間分（4つのスロット）
        
        # 範囲内に予約済みスロットがあるかチェック
        for i in range(start_index, end_index + 1):
            if i < len(time_slots):
                is_disabled = time_slots[i].get_attribute("data-disabled") == "true"
                if is_disabled:
                    return True
        
        return False
    except Exception as e:
        print(f"  予約状況の確認中にエラーが発生しました: {e}")
        return False  # エラーの場合は予約済みでないと仮定

def set_time_range(page, start_hour, start_minute, end_hour, end_minute):
    """開始・終了時間を設定する"""
    try:
        # 開始時間のプルダウンを選択
        start_hour_select = page.locator('select[aria-label="開始時"]')
        
        # プルダウンの選択肢を確認
        start_hour_options = start_hour_select.evaluate("""(element) => {
            return Array.from(element.options).map(option => option.value);
        }""")
        
        # 選択肢に指定した時間があるか確認
        if str(start_hour) not in start_hour_options:
            print(f"  開始時間 {start_hour}:00 は選択肢にありません")
            return False
        
        # 開始時間を選択
        start_hour_select.select_option(value=str(start_hour))
        
        # 開始分を選択
        start_minute_select = page.locator('select[aria-label="開始分"]')
        start_minute_select.select_option(value=f"{start_minute:02d}")
        
        # 終了時間のプルダウンを選択
        end_hour_select = page.locator('select[aria-label="終了時"]')
        
        # プルダウンの選択肢を確認
        end_hour_options = end_hour_select.evaluate("""(element) => {
            return Array.from(element.options).map(option => option.value);
        }""")
        
        # 選択肢に指定した時間があるか確認
        if str(end_hour) not in end_hour_options:
            print(f"  終了時間 {end_hour}:00 は選択肢にありません")
            return False
        
        # 終了時間を選択
        end_hour_select.select_option(value=str(end_hour))
        
        # 終了分を選択
        end_minute_select = page.locator('select[aria-label="終了分"]')
        end_minute_select.select_option(value=f"{end_minute:02d}")
        
        # 少し待機して料金が更新されるのを待つ
        time.sleep(1.5)
        return True
    except Exception as e:
        print(f"  時間選択でエラーが発生しました: {e}")
        return False

def get_available_plans(page, label):
    """指定された日時で利用可能なプラン情報を取得する"""
    plans = []
    
    try:
        # プラン情報を取得（li要素を直接取得）
        plan_elements = page.query_selector_all("ul.css-n9qrp8 > li")
        
        # 利用可能なプラン数をカウント
        available_plans = 0
        for plan in plan_elements:
            if plan.get_attribute("class") != "css-1cpdoqx":
                available_plans += 1
        
        # ログに実際の時間帯表示を含める
        actual_time_range = page.locator('div.css-1u9gb7i').inner_text()
        print(f"  {label}で利用可能なプラン数: {available_plans}/{len(plan_elements)}")
        print(f"  実際の時間枠表示: {actual_time_range}")
        
        for i, plan in enumerate(plan_elements):
            try:
                # プラン名を取得
                plan_name_element = plan.query_selector("span.css-k6zetj")
                if plan_name_element:
                    plan_name = plan_name_element.inner_text()
                    
                    # 最低利用時間を取得
                    min_hours_element = plan.query_selector("span.css-1j0pr6n")
                    min_hours = min_hours_element.inner_text() if min_hours_element else ""
                    
                    # 無効状態かどうかを確認
                    is_disabled = plan.get_attribute("class") == "css-1cpdoqx"
                    
                    # 料金要素を取得（複数のクラスに対応）
                    price_info = get_price_info(plan)
                    
                    plans.append({
                        'id': i,
                        'name': plan_name,
                        'min_hours': min_hours,
                        'is_disabled': is_disabled,
                        'price_info': price_info
                    })
            except Exception as e:
                print(f"  プラン情報の取得中にエラーが発生しました: {e}")
                
    except Exception as e:
        print(f"  プラン情報取得でエラーが発生しました: {e}")
    
    return plans

def get_price_info(plan_element):
    """プラン要素から料金情報を取得する"""
    price_info = {
        'type': None,
        'text': "価格不明",
        'value': None
    }
    
    try:
        # まず通常料金（セール前）を探す
        price_element = plan_element.query_selector("span.css-1sq1blk")
        if price_element:
            price_info['type'] = "通常価格"
            price_info['text'] = price_element.inner_text()
            
            # 割引後価格があるか探す（セール表示の場合）
            discount_element = plan_element.query_selector("span.css-d362cm")
            if discount_element:
                price_info['discount_text'] = discount_element.inner_text()
                
                # 割引率を取得
                discount_rate_element = plan_element.query_selector("span.css-hdwjef")
                if discount_rate_element:
                    price_info['discount_rate'] = discount_rate_element.inner_text()
        
        # 通常料金が見つからなければ割引後価格を探す
        elif not price_element:
            price_element = plan_element.query_selector("span.css-d362cm")
            if price_element:
                price_info['type'] = "割引後価格"
                price_info['text'] = price_element.inner_text()
        
        # さらに見つからなければ通常の料金表示を探す
        if not price_element:
            price_element = plan_element.query_selector("span.css-1y4ezd0")
            if price_element:
                price_info['type'] = "表示価格"
                price_info['text'] = price_element.inner_text()
        
        # 価格が見つかった場合、数値を抽出
        if price_info['type']:
            price_info['value'] = int(''.join(filter(str.isdigit, price_info['text'])))
    except Exception as e:
        print(f"  料金情報の取得中にエラーが発生しました: {e}")
    
    return price_info

def get_prices_for_plans(page, plans):
    """各プランの料金を取得する"""
    # 各プランの料金を取得
    plan_prices = {}
    
    for plan in plans:
        if plan['price_info']['value']:
            plan_prices[plan['name']] = plan['price_info']['value']
            
            status = " (無効状態)" if plan['is_disabled'] else ""
            price_type = plan['price_info']['type'] or "表示価格"
            price_text = plan['price_info']['text']
            
            print(f"  プラン: {plan['name']} - {price_type}: {price_text}{status}")
    
    return plan_prices

def print_price_table(all_price_data):
    """料金データを表形式で表示"""
    print("\n===== 1週間分の料金情報 =====")
    
    for date, time_slots in all_price_data.items():
        print(f"\n【{date}】")
        
        if not time_slots:
            print("  料金情報はありません")
            continue
        
        # 各時間帯の料金を表示
        for time_slot, prices in time_slots.items():
            if prices:
                print(f"  時間帯: {time_slot}")
                for plan_name, price in prices.items():
                    print(f"    {plan_name}: ¥{price:,}")

def save_to_csv(all_price_data, all_plan_names):
    """料金データをCSVに保存"""
    # データフレーム用のリストを作成
    data_rows = []
    
    # データを整形
    for date, time_slots in all_price_data.items():
        for time_slot, prices in time_slots.items():
            if prices:
                row = {'日付': date, '時間帯': time_slot}
                
                # 各プランの料金を追加
                for plan_name in all_plan_names:
                    row[plan_name] = prices.get(plan_name, None)
                
                data_rows.append(row)
    
    # データフレームを作成
    if data_rows:
        df = pd.DataFrame(data_rows)
        
        # 単位を追加（各プラン列に「円」を追加）
        for plan_name in all_plan_names:
            if plan_name in df.columns:
                df[plan_name] = df[plan_name].apply(lambda x: f"{int(x):,}円" if pd.notnull(x) else "")
        
        # CSVに保存
        filename = f"spacemarket_prices_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        df.to_csv(filename, index=False, encoding='utf-8-sig')
        print(f"\nCSVファイルに保存しました: {filename}")
    else:
        print("\nデータがないため、CSVは作成されませんでした")

if __name__ == "__main__":
    main()