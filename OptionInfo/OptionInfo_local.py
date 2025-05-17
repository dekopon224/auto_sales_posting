import requests
from bs4 import BeautifulSoup

def get_options_from_url(url):
    try:
        # URLからHTMLコンテンツを取得
        print(f"URLからデータを取得中: {url}")
        response = requests.get(url)
        
        # リクエストが成功したかチェック
        if response.status_code == 200:
            print(f"ステータスコード: {response.status_code} - 成功")
            
            # BeautifulSoupを使用してHTMLを解析
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # オプションセクションを探す
            options_section = soup.find('h2', id='room-options')
            
            if not options_section:
                print("オプションセクションが見つかりませんでした")
                return
            
            # オプションリストを探す
            options_list = options_section.find_next('ul', class_='css-1gjx5c5')
            
            if not options_list:
                print("オプションリストが見つかりませんでした")
                return
            
            # 各オプション項目を見つける
            option_items = options_list.find_all('li', class_='css-zzxv54')
            
            print("\n===== オプション一覧 =====\n")
            
            for index, item in enumerate(option_items, 1):
                # オプション名を取得
                name_tag = item.find('p', class_='css-l8u2g2')
                name = name_tag.text.strip() if name_tag else "不明"
                
                # 価格を取得
                price_tag = name_tag.find_next('p', class_='css-0') if name_tag else None
                price = price_tag.text.strip() if price_tag else "不明"
                
                print(f"オプション {index}:")
                print(f"  名前: {name}")
                print(f"  価格: {price}")
                print()
            
            print(f"合計 {len(option_items)} 件のオプションが見つかりました")
            
        else:
            print(f"エラー: ステータスコード {response.status_code} が返されました")
        
    except requests.exceptions.RequestException as e:
        print(f"リクエスト中にエラーが発生しました: {e}")

# URLを指定してオプション情報を取得
if __name__ == "__main__":
    url = "https://www.spacemarket.com/spaces/dcfsa_rj0ojpnpdk/?room_uid=f4l-ByT2WMODjjNB"
    get_options_from_url(url)