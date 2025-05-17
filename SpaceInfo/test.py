import requests
from bs4 import BeautifulSoup
import re

def scrape_space_market(url):
    try:
        # URLからHTMLを取得
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.get(url, headers=headers)
        response.raise_for_status()  # HTTPエラーがあれば例外を発生させる
        
        # BeautifulSoupでHTMLを解析
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # スペース名を取得
        space_name = soup.find('h1', class_='css-cftpp3')
        if not space_name:
            space_name = soup.find('h1')  # クラス名がない場合はh1タグだけで探す
        
        space_name_text = space_name.text.strip() if space_name else "スペース名が見つかりません"
        
        # 各情報を保存する辞書
        info_dict = {}
        
        # 各行（tr）を処理
        rows = soup.find_all('tr', class_='css-0')
        if not rows:
            rows = soup.find_all('tr')  # クラス名がない場合はtrタグだけで探す
            
        for row in rows:
            # 各行からラベルを取得
            label_elem = row.find('span', class_='css-ygxe26')
            if not label_elem:
                # クラスが見つからない場合は、最初のtdのspanを試す
                td_elems = row.find_all('td')
                if td_elems and len(td_elems) > 0:
                    label_elem = td_elems[0].find('span')
            
            if not label_elem:
                continue
                
            label = label_elem.text.strip()
            
            # 値を取得（2番目のtdから）
            td_elems = row.find_all('td')
            if len(td_elems) > 1:
                value = td_elems[1].text.strip()
                info_dict[label] = value
        
        # 定員人数を分割する処理
        capacity_text = info_dict.get('定員人数', '')
        capacity_count = "N/A"
        capacity_seated = "N/A"
        capacity_area = "N/A"
        
        if capacity_text:
            # 収容人数（XX人収容）を抽出
            capacity_match = re.search(r'(\d+)人収容', capacity_text)
            if capacity_match:
                capacity_count = f"{capacity_match.group(1)}人収容"
            
            # 着席可能人数（YY人着席可能）を抽出
            seated_match = re.search(r'(\d+)人着席可能', capacity_text)
            if seated_match:
                capacity_seated = f"{seated_match.group(1)}人着席可能"
            
            # 広さ（ZZ㎡）を抽出
            area_match = re.search(r'(\d+)㎡', capacity_text)
            if area_match:
                capacity_area = f"{area_match.group(1)}㎡"
        
        # 結果をログに出力
        print("\n===== スペース情報 =====")
        print(f"スペース名: {space_name_text}")
        print(f"住所: {info_dict.get('住所', 'N/A')}")
        print(f"最寄駅: {info_dict.get('最寄駅', 'N/A')}")
        print(f"定員人数(人数): {capacity_count}")
        print(f"定員人数(着席可能人数): {capacity_seated}")
        print(f"定員人数(広さ): {capacity_area}")
        print(f"会場タイプ: {info_dict.get('会場タイプ', 'N/A')}")
        
        return True
        
    except Exception as e:
        print(f"エラーが発生しました: {e}")
        return False

def main():
    print("スペースマーケット情報スクレイパー")
    print("-----------------------------------")
    
    while True:
        # URLの入力を受け付ける
        url = input("\nスペースマーケットのURLを入力してください（終了するには 'q' を入力）: ")
        
        if url.lower() == 'q':
            print("プログラムを終了します。")
            break
            
        # URLのバリデーション（簡易的なもの）
        if not url.startswith('http'):
            print("有効なURLを入力してください（https:// または http:// で始まるURL）")
            continue
            
        # スクレイピング実行
        success = scrape_space_market(url)
        
        if not success:
            print("スクレイピングに失敗しました。URLが正しいか確認してください。")

if __name__ == "__main__":
    main()