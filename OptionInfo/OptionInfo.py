import boto3
import requests
import json
from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta

dynamodb = boto3.resource("dynamodb")
info_table = dynamodb.Table("OptionInfo")
history_table = dynamodb.Table("OptionPriceHistory")

def get_current_timestamp_jst():
    JST = timezone(timedelta(hours=9))
    return datetime.now(JST).isoformat()

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

def get_options_from_url(url):
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/112.0.0.0 Safari/537.36'
        }
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        # room_idを取得
        room_id = extract_room_id_from_soup(soup)

        options_section = soup.find("h2", id="room-options")
        if not options_section:
            return [], "不明", room_id

        options_list = options_section.find_next("ul", class_="css-1gjx5c5")
        if not options_list:
            return [], "不明", room_id

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

        return options, extract_space_name(soup), room_id

    except requests.exceptions.RequestException as e:
        print(f"リクエストエラー: {e}")
        return [], "不明", None

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

def process_single_url(url, now):
    """単一URLの処理"""
    result = {
        "url": url,
        "success": False,
        "room_id": None,
        "options_count": 0,
        "changes_count": 0,
        "error": None
    }
    
    try:
        new_options, name, room_id = get_options_from_url(url)
        if not room_id:
            result["error"] = "ページから room_id が取得できませんでした"
            return result
        
        result["room_id"] = room_id

        # 旧データの取得
        try:
            response = info_table.get_item(Key={"spaceId": room_id})
            old_item = response.get("Item")
            old_options = old_item.get("options", []) if old_item else []
        except Exception as e:
            print(f"旧データ取得失敗 (room_id: {room_id}): {e}")
            old_options = []

        # 差分チェック
        changes = detect_price_changes(old_options, new_options)

        # 差分があれば履歴テーブルに追加
        for change in changes:
            try:
                history_table.put_item(Item={
                    "spaceId": room_id,
                    "timestamp": now,
                    "optionName": change["optionName"],
                    "oldPrice": change["oldPrice"],
                    "newPrice": change["newPrice"],
                    "url": url
                })
                print(f"[履歴保存] {room_id}: {change['optionName']} {change['oldPrice']} → {change['newPrice']}")
            except Exception as e:
                print(f"履歴保存エラー (room_id: {room_id}): {e}")

        # OptionInfo上書き
        item = {
            "spaceId": room_id,
            "name": name,
            "url": url,
            "options": new_options,
            "createdAt": now
        }

        try:
            info_table.put_item(Item=item)
            print(f"OptionInfo保存成功 (room_id: {room_id}): {len(new_options)}件保存、{len(changes)}件履歴登録")
            result["success"] = True
            result["options_count"] = len(new_options)
            result["changes_count"] = len(changes)
        except Exception as e:
            print(f"DynamoDB保存エラー (room_id: {room_id}): {e}")
            result["error"] = f"DynamoDB保存エラー: {str(e)}"
            
    except Exception as e:
        print(f"URL処理エラー ({url}): {e}")
        result["error"] = f"URL処理エラー: {str(e)}"
    
    return result

def lambda_handler(event, context):
    # API Gatewayからのリクエストの場合、bodyをパースする必要がある
    if "body" in event:
        try:
            # event["body"]はJSON文字列なので、パースする
            body = json.loads(event["body"])
        except json.JSONDecodeError:
            return {"statusCode": 400, "body": "無効なJSONフォーマットです"}
    else:
        # 直接呼び出しの場合（テスト等）
        body = event
    
    # 単一URL形式と複数URL形式の両方をサポート
    urls = []
    if "url" in body:
        # 単一URL形式 {"url": "..."}
        urls = [body["url"]]
    elif "urls" in body:
        # 複数URL形式 {"urls": ["...", "...", "..."]}
        urls = body["urls"]
    else:
        return {"statusCode": 400, "body": "url または urls が不足しています"}

    if not urls:
        return {"statusCode": 400, "body": "処理するURLがありません"}

    now = get_current_timestamp_jst()
    results = []
    
    # 各URLを処理
    for url in urls:
        print(f"処理開始: {url}")
        result = process_single_url(url, now)
        results.append(result)
    
    # 結果集計
    total_success = sum(1 for r in results if r["success"])
    total_options = sum(r["options_count"] for r in results if r["success"])
    total_changes = sum(r["changes_count"] for r in results if r["success"])
    total_errors = sum(1 for r in results if not r["success"])
    
    # レスポンスもJSON文字列として返す
    response_body = {
        "summary": f"処理完了: {total_success}件成功, {total_errors}件エラー, 合計{total_options}件保存, {total_changes}件履歴登録",
        "total_urls": len(urls),
        "successful_urls": total_success,
        "failed_urls": total_errors,
        "total_options_saved": total_options,
        "total_changes_logged": total_changes,
        "details": results
    }
    
    return {
        "statusCode": 200,
        "body": json.dumps(response_body, ensure_ascii=False)  # JSON文字列として返す
    }