import boto3
import json
from decimal import Decimal
from datetime import datetime, timedelta

def decimal_to_float(obj):
    """DynamoDBのDecimal型をfloatに変換"""
    if isinstance(obj, Decimal):
        return float(obj)
    return obj

def lambda_handler(event, context):
    if 'body' in event:
        try:
            body = json.loads(event['body'])
        except:
            return {
                'statusCode': 400,
                'body': json.dumps({'error': 'Invalid request body'})
            }
    else:
        body = event
    
    room_ids = body.get("room_ids", [])
    if not room_ids:
        return {
            'statusCode': 400,
            'body': json.dumps({'error': 'room_ids が不足しています'})
        }

    dynamodb = boto3.resource('dynamodb')
    table = dynamodb.Table('SpaceInfo')
    
    # 1週間分の日付を生成（今日から）
    today = datetime.now()
    dates = [(today + timedelta(days=i)).strftime('%Y-%m-%d') for i in range(7)]
    
    rooms_data = []
    
    try:
        # 各room_idについて処理
        for room_id in room_ids:
            # BatchGetItemで複数の日付のデータを一度に取得
            request_items = {
                'SpaceInfo': {
                    'Keys': [
                        {'spaceId': room_id, 'date': date} 
                        for date in dates
                    ]
                }
            }
            
            response = dynamodb.batch_get_item(RequestItems=request_items)
            items = response.get('Responses', {}).get('SpaceInfo', [])
            
            if not items:
                # データが見つからない場合
                rooms_data.append({
                    "room_id": room_id,
                    "found": False,
                    "error": "データが見つかりません"
                })
                continue
            
            # 最初のアイテムから基本情報を取得
            first_item = items[0]
            
            # 日付ごとのポイントデータを整理
            daily_points = []
            for item in items:
                daily_points.append({
                    "date": item['date'],
                    "point": decimal_to_float(item.get('point', 0))
                })
            
            # 日付順でソート
            daily_points.sort(key=lambda x: x['date'])
            
            room_data = {
                "room_id": room_id,
                "found": True,
                "name": first_item.get('name', 'N/A'),
                "url": first_item.get('url', 'N/A'),
                "location": first_item.get('location', 'N/A'),
                "station": first_item.get('station', 'N/A'),
                "capacity": first_item.get('capacity', 'N/A'),
                "stay_capacity": first_item.get('stay_capacity', 'N/A'),
                "floor_space": first_item.get('floor_space', 'N/A'),
                "space_type": first_item.get('space_type', 'N/A'),
                "daily_points": daily_points,
                "total_records": len(items)
            }
            
            rooms_data.append(room_data)
    
    except Exception as e:
        return {
            'statusCode': 500,
            'body': json.dumps({
                'error': f"データ取得エラー: {str(e)}"
            })
        }
    
    # 結果サマリー
    found_rooms = [room for room in rooms_data if room.get('found', False)]
    not_found_rooms = [room for room in rooms_data if not room.get('found', False)]
    
    response_body = {
        "summary": {
            "requested_rooms": len(room_ids),
            "found_rooms": len(found_rooms),
            "not_found_rooms": len(not_found_rooms)
        },
        "rooms": rooms_data
    }
    
    return {
        'statusCode': 200,
        'body': json.dumps(response_body, ensure_ascii=False, default=decimal_to_float)
    }