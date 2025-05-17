import boto3
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse, parse_qs

dynamodb = boto3.resource("dynamodb")
info_table = dynamodb.Table("OptionInfo")
history_table = dynamodb.Table("OptionPriceHistory")

def get_current_timestamp_jst():
    JST = timezone(timedelta(hours=9))
    return datetime.now(JST).isoformat()

def extract_space_id_from_url(url):
    parsed = urlparse(url)
    query_params = parse_qs(parsed.query)
    return query_params.get("room_uid", [None])[0]

def get_options_from_url(url):
    try:
        response = requests.get(url)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        options_section = soup.find("h2", id="room-options")
        if not options_section:
            return [], "不明"

        options_list = options_section.find_next("ul", class_="css-1gjx5c5")
        if not options_list:
            return [], "不明"

        option_items = options_list.find_all("li", class_="css-zzxv54")

        options = []
        for item in option_items:
            name_tag = item.find("p", class_="css-l8u2g2")
            name = name_tag.text.strip() if name_tag else "不明"

            price_tag = name_tag.find_next("p", class_="css-0") if name_tag else None
            price = price_tag.text.strip() if price_tag else "不明"

            options.append({
                "name": name,
                "price": price
            })

        return options, extract_space_name(soup)

    except requests.exceptions.RequestException as e:
        print(f"リクエストエラー: {e}")
        return [], "不明"

def extract_space_name(soup):
    title_tag = soup.find("title")
    return title_tag.text.strip() if title_tag else "不明"

def detect_price_changes(old_options, new_options):
    old_map = {o["name"]: o["price"] for o in old_options}
    changes = []

    for new in new_options:
        name = new["name"]
        new_price = new["price"]
        old_price = old_map.get(name)
        if old_price and old_price != new_price:
            changes.append({
                "optionName": name,
                "oldPrice": old_price,
                "newPrice": new_price
            })
    return changes

def lambda_handler(event, context):
    url = event.get("url")
    if not url:
        return {"statusCode": 400, "body": "url が不足しています"}

    space_id = extract_space_id_from_url(url)
    if not space_id:
        return {"statusCode": 400, "body": "URL から spaceId (room_uid) が取得できませんでした"}

    new_options, name = get_options_from_url(url)
    now = get_current_timestamp_jst()

    # 旧データの取得
    try:
        response = info_table.get_item(Key={"spaceId": space_id})
        old_item = response.get("Item")
        old_options = old_item.get("options", []) if old_item else []
    except Exception as e:
        print(f"旧データ取得失敗: {e}")
        old_options = []

    # 差分チェック
    changes = detect_price_changes(old_options, new_options)

    # 差分があれば履歴テーブルに追加
    for change in changes:
        try:
            history_table.put_item(Item={
                "spaceId": space_id,
                "timestamp": now,
                "optionName": change["optionName"],
                "oldPrice": change["oldPrice"],
                "newPrice": change["newPrice"],
                "url": url
            })
            print(f"[履歴保存] {change['optionName']} {change['oldPrice']} → {change['newPrice']}")
        except Exception as e:
            print(f"履歴保存エラー: {e}")

    # OptionInfo上書き
    item = {
        "spaceId": space_id,
        "name": name,
        "url": url,
        "options": new_options,
        "createdAt": now
    }

    try:
        info_table.put_item(Item=item)
        print(f"OptionInfo保存成功: {item}")
        return {"statusCode": 200, "body": f"{len(new_options)}件保存、{len(changes)}件履歴登録"}
    except Exception as e:
        print(f"DynamoDB保存エラー: {e}")
        return {"statusCode": 500, "body": "保存に失敗しました"}
