import boto3
import requests
from bs4 import BeautifulSoup
import re
from datetime import datetime, timedelta, timezone
import time
from urllib.parse import urlparse, parse_qs

def lambda_handler(event, context):
    # 対象URL（手動で指定）
    url = "https://www.spacemarket.com/spaces/dcfsa_rj0ojpnpdk/?room_uid=f4l-ByT2WMODjjNB"  # ←ここを実際のURLに変更！

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

        # 1週間分のデータを生成
        for i in range(7):
            target_date = now + timedelta(days=i)
            date_str = target_date.strftime('%Y-%m-%d')
            created_at = target_date.isoformat()
            expire_at = int(time.mktime((target_date + timedelta(days=7)).timetuple()))

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
                'point': 1,  # 仮のポイント。将来的にはロジックで算出
                'createdAt': created_at,
                'expireAt': expire_at
            }

            table.put_item(Item=item)

        return {
            'statusCode': 200,
            'body': f"{space_name_text} のデータを {now.strftime('%Y-%m-%d')} から1週間分登録しました。"
        }

    except Exception as e:
        return {
            'statusCode': 500,
            'body': f"エラーが発生しました: {str(e)}"
        }