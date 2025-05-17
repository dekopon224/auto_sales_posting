import boto3
import requests
from bs4 import BeautifulSoup
import re
from datetime import datetime, timedelta, timezone
import time
from urllib.parse import urlparse, parse_qs
import json
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

    headers = {
        'User-Agent': 'Mozilla/5.0'
    }

    # DynamoDB テーブル名
    table_name = 'SpaceInfo'
    table = boto3.resource('dynamodb').Table(table_name)

    # JSTで現在時刻を取得
    JST = timezone(timedelta(hours=9))
    now = datetime.now(JST)

    try:
        # まずBeautifulSoupで基本情報を取得
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')

        # スペース名
        space_name = soup.find('h1', class_='css-cftpp3') or soup.find('h1')
        space_name_text = space_name.text.strip() if space_name else "名称未取得"

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
        area_match = re.search(r'(\d+)', capacity_text)
        parsed_url = urlparse(url)
        query_params = parse_qs(parsed_url.query)
        space_id = query_params.get('room_uid', ['unknown'])[0]

        # Playwrightを使用してポイント情報を取得
        points_data = get_points_data(url)

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
                'floor_space': area_match.group(0) + '㎡' if area_match else 'N/A',
                'space_type': info_dict.get('会場タイプ', 'N/A'),
                'excludedMorning': False,
                'point': point,  # 算出したポイント
                'createdAt': created_at,
                'expireAt': expire_at
            }

            table.put_item(Item=item)

        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': f"{space_name_text} のデータを {now.strftime('%Y-%m-%d')} から1週間分登録しました。"
            })
        }

    except Exception as e:
        return {
            'statusCode': 500,
            'body': json.dumps({
                'error': f"エラーが発生しました: {str(e)}"
            })
        }

def get_points_data(url):
    """Playwrightを使用してポイント情報を取得する関数"""
    print(f"URLにアクセス中: {url}")
    
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
            response = page.goto(url, wait_until='networkidle', timeout=90000)
            
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
            browser.close()