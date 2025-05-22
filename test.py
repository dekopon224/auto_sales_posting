import requests
import os
from urllib.parse import urlparse

def fetch_and_save_html(url, filename=None):
    """
    指定されたURLからHTMLを取得して、同じディレクトリに保存する
    
    Args:
        url (str): 取得するHTMLのURL
        filename (str, optional): 保存するファイル名。指定されない場合はURLから自動生成
    """
    # User-Agentを設定
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/112.0.0.0 Safari/537.36'
    }
    
    try:
        # HTMLを取得
        print(f"HTMLを取得中: {url}")
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()  # HTTPエラーをチェック
        
        # ファイル名を決定
        if filename is None:
            # URLからファイル名を生成
            parsed_url = urlparse(url)
            domain = parsed_url.netloc.replace('www.', '')
            filename = f"{domain}.html"
        
        # 現在のディレクトリに保存
        filepath = os.path.join(os.getcwd(), filename)
        
        # HTMLファイルを保存
        with open(filepath, 'w', encoding='utf-8') as file:
            file.write(response.text)
        
        print(f"HTMLを保存しました: {filepath}")
        print(f"ファイルサイズ: {len(response.text)} 文字")
        
        return filepath
        
    except requests.exceptions.RequestException as e:
        print(f"リクエストエラー: {e}")
        return None
    except IOError as e:
        print(f"ファイル保存エラー: {e}")
        return None

# 使用例
if __name__ == "__main__":
    # 取得したいURL
    target_url = "https://spacemarket.com/p/t-sTdvRWuIXO2T3q"
    
    # HTMLを取得して保存
    saved_file = fetch_and_save_html(target_url)
    
    if saved_file:
        print("処理が完了しました。")
    else:
        print("処理に失敗しました。")
    
    # カスタムファイル名で保存する場合の例
    # saved_file = fetch_and_save_html("https://example.com", "custom_name.html")