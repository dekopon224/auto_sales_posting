import boto3
import requests
from bs4 import BeautifulSoup
import re
from datetime import datetime, timedelta, timezone
import time
import json
from playwright.sync_api import sync_playwright
from boto3.dynamodb.conditions import Key

def extract_room_id_from_soup(soup):
    try:
        script_tag = soup.find("script", id="__NEXT_DATA__")
        if not script_tag:
            return None
        
        json_data = json.loads(script_tag.string)
        room_id = json_data.get("props", {}).get("pageProps", {}).get("data", {}).get("room", {}).get("id")
        return room_id
    except (json.JSONDecodeError, AttributeError, KeyError) as e:
        print(f"room_id取得エラー: {e}")
        return None

def process_single_url(url, now, page=None):
    """単一URLの処理"""
    result = {
        "url": url,
        "success": False,
        "space_id": None,
        "space_name": None,
        "error": None
    }
    
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0'
        }

        table = boto3.resource('dynamodb').Table('SpaceInfo')

        response = requests.get(url, headers=headers)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')

        # スペース名
        space_name = soup.find('h1', class_='css-cftpp3') or soup.find('h1')
        space_name_text = space_name.text.strip() if space_name else "名称未取得"
        result["space_name"] = space_name_text

        # テーブルデータ抽出
        info_dict = {}
        rows = soup.find_all('tr', class_='css-0') or soup.find_all('tr')
        for row in rows:
            label_elem = row.find('span', class_='css-ygxe26')
            if not label_elem:
                td_elems = row.find_all('td')
                if td_elems:
                    label_elem = td_elems[0].find('span')
            if not label_elem:
                continue
            label = label_elem.text.strip()
            value = row.find_all('td')[1].text.strip() if len(row.find_all('td')) > 1 else ''
            info_dict[label] = value

        # 定員人数など
        capacity_text = info_dict.get('定員人数', '')
        capacity_match = re.search(r'(\d+)人収容', capacity_text)
        seated_match = re.search(r'(\d+)人着席可能', capacity_text)
        area_match = re.search(r'(\d+(?:\.\d+)?)㎡', capacity_text)
        
        # HTMLスクリプトタグからroom_idを取得
        space_id = extract_room_id_from_soup(soup)
        if not space_id:
            space_id = 'unknown'
        result["space_id"] = space_id

        # ===== 追加：古いデータを削除 =====
        # 今日の日付を取得
        today_str = now.strftime('%Y-%m-%d')
        
        # このspaceIdの全データを取得して、前日以前のものを削除
        try:
            # spaceIdでクエリ
            response = table.query(
                KeyConditionExpression=Key('spaceId').eq(space_id)
            )
            
            # 前日以前のデータを削除
            with table.batch_writer() as batch:
                for item in response.get('Items', []):
                    if item['date'] < today_str:
                        batch.delete_item(
                            Key={
                                'spaceId': item['spaceId'],
                                'date': item['date']
                            }
                        )
                        print(f"削除: spaceId={item['spaceId']}, date={item['date']}")
            
            # ページネーション対応
            while 'LastEvaluatedKey' in response:
                response = table.query(
                    KeyConditionExpression=Key('spaceId').eq(space_id),
                    ExclusiveStartKey=response['LastEvaluatedKey']
                )
                
                with table.batch_writer() as batch:
                    for item in response.get('Items', []):
                        if item['date'] < today_str:
                            batch.delete_item(
                                Key={
                                    'spaceId': item['spaceId'],
                                    'date': item['date']
                                }
                            )
                            print(f"削除: spaceId={item['spaceId']}, date={item['date']}")
                            
        except Exception as e:
            print(f"古いデータの削除中にエラー: {e}")
        # ===== 追加ここまで =====

        # Playwrightを使用してポイント情報を取得
        points_data = get_points_data(url, page)

        # 1週間分のデータを生成
        for i in range(7):
            target_date = now + timedelta(days=i)
            date_str = target_date.strftime('%Y-%m-%d')
            created_at = target_date.isoformat()
            expire_at = int(time.mktime((target_date + timedelta(days=7)).timetuple()))

            # その日付のポイントを取得（該当する日付がない場合はデフォルト値1を使用）
            point = 1  # デフォルト値
            for data_item in points_data:
                if data_item['date'] == date_str:
                    point = data_item['point']
                    break

            item = {
                'spaceId': space_id,
                'date': date_str,
                'name': space_name_text,
                'url': url,
                'location': info_dict.get('住所', 'N/A'),
                'station': info_dict.get('最寄駅', 'N/A'),
                'capacity': capacity_match.group(0) if capacity_match else 'N/A',
                'stay_capacity': seated_match.group(0) if seated_match else 'N/A',
                'floor_space': area_match.group(0) if area_match else 'N/A',
                'space_type': info_dict.get('会場タイプ', 'N/A'),
                'point': point,
                'createdAt': created_at,
                'expireAt': expire_at
            }

            table.put_item(Item=item)

        result["success"] = True
        
    except Exception as e:
        print(f"URL処理エラー ({url}): {e}")
        result["error"] = f"URL処理エラー: {str(e)}"
    
    return result

def lambda_handler(event, context):
    # SQSからメッセージを受信
    JST = timezone(timedelta(hours=9))
    now = datetime.now(JST)
    
    results = []
    
    # ブラウザを一度だけ作成して全URLで共有
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
            for record in event['Records']:
                try:
                    # SQSメッセージからデータを取得
                    message_body = json.loads(record['body'])
                    urls = message_body.get('urls', [])
                    
                    print(f"処理開始: {len(urls)}件のURL")
                    
                    # 各URLを処理
                    for url in urls:
                        print(f"処理中: {url}")
                        result = process_single_url(url, now, page)
                        results.append(result)
                    
                    # 結果をログに出力
                    total_success = sum(1 for r in results if r["success"])
                    total_errors = sum(1 for r in results if not r["success"])
                    successful_spaces = [r["space_name"] for r in results if r["success"] and r["space_name"]]
                    
                    print(f"処理完了: {total_success}件成功, {total_errors}件エラー")
                    print(f"成功したスペース: {', '.join(successful_spaces)}")
                    
                except Exception as e:
                    print(f"メッセージ処理エラー: {e}")
        finally:
            browser.close()
    
    return {
        'statusCode': 200,
        'body': json.dumps({
            'processed_messages': len(event['Records']),
            'processed_urls': len(results),
            'successful_urls': sum(1 for r in results if r["success"])
        })
    }

def get_points_data(url, page=None, should_close_browser=False):
    """Playwrightを使用してポイント情報を取得する関数"""
    print(f"URLにアクセス中: {url}")
    
    # ページが渡されない場合は新しいブラウザを作成
    if page is None:
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
            should_close_browser = True
    
    try:
        # リトライ機能付きでページを読み込み
        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = page.goto(url, wait_until='networkidle', timeout=30000)
                break
            except Exception as e:
                if attempt == max_retries - 1:
                    raise e
                print(f"ページ読み込み失敗 (試行 {attempt + 1}/{max_retries}): {str(e)}")
                time.sleep(2)
        
        if not response.ok:
            print(f"ページロードエラー: {response.status} {response.status_text}")
            return []
        
        try:
            page.wait_for_selector('.css-j3mvlq', timeout=10000)
        except Exception as e:
            print(f"要素 '.css-j3mvlq' が見つかりませんでした: {str(e)}")
            return []
        
        # データを抽出し、記号をポイントに変換
        data = page.evaluate('''() => {
                const buttons = document.querySelectorAll('.css-j3mvlq button');
                if (!buttons || buttons.length === 0) {
                    return [];
                }
                
                return Array.from(buttons).map(button => {
                    const day = button.querySelector('.css-7tvow, .css-qo22pl, .css-1fvi6cv')?.textContent || "";
                    const date = button.querySelector('.css-lw8eys, .css-b91hki, .css-19jz4op')?.textContent || "";
                    
                    // 記号をポイント(数値)に変換
                    let point = 0; // デフォルトは0
                    
                    if (button.querySelector('.icon-spm-double-circle')) {
                        point = 0; // 二重丸は0
                    } else if (button.querySelector('.icon-spm-single-circle')) {
                        point = 1; // 丸は1
                    } else if (button.querySelector('.icon-spm-triangle')) {
                        point = 2; // 三角は2
                    } // それ以外はデフォルトの0のまま
                    
                    return { day, date, point };
                });
            }''')
        
        if not data or len(data) == 0:
            print("指定した要素から日付と記号を取得できませんでした。")
            return []
        
        # 日付フォーマットを整形 (例: "5/14" -> "2025-05-14")
        formatted_data = []
        current_year = datetime.now().year
        for item in data:
            if item['date']:
                try:
                    month, day = item['date'].split('/')
                    formatted_date = f"{current_year}-{month.zfill(2)}-{day.zfill(2)}"
                    formatted_data.append({
                        'day': item['day'],
                        'date': formatted_date,
                        'point': item['point']
                    })
                except Exception as e:
                    print(f"日付フォーマットエラー: {str(e)} - {item['date']}")
            
        return formatted_data
        
    except Exception as e:
        print(f"スクレイピング中にエラーが発生しました: {str(e)}")
        import traceback
        print(traceback.format_exc())
        return []
    finally:
        if should_close_browser and 'browser' in locals():
            browser.close()