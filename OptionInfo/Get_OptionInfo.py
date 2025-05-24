import json
import boto3
from boto3.dynamodb.conditions import Key
from decimal import Decimal

# DynamoDBクライアントの初期化
dynamodb = boto3.resource('dynamodb')
info_table = dynamodb.Table('OptionInfo')
history_table = dynamodb.Table('OptionPriceHistory')

class DecimalEncoder(json.JSONEncoder):
    """DynamoDBのDecimal型をJSONでシリアライズするためのエンコーダー"""
    def default(self, obj):
        if isinstance(obj, Decimal):
            return int(obj)
        return super(DecimalEncoder, self).default(obj)

def get_price_history(space_id, limit=10):
    """
    指定されたspaceIdの価格変更履歴を取得する
    
    Args:
        space_id (str): スペースID
        limit (int): 取得する履歴の最大件数（デフォルト10件）
    
    Returns:
        list: 価格変更履歴のリスト
    """
    try:
        response = history_table.query(
            KeyConditionExpression=Key('spaceId').eq(str(space_id)),
            ScanIndexForward=False,  # 降順（最新順）
            Limit=limit
        )
        
        history_items = []
        for item in response.get('Items', []):
            history_item = {
                'timestamp': item.get('timestamp'),
                'optionName': item.get('optionName'),
                'oldPrice': item.get('oldPrice'),
                'newPrice': item.get('newPrice')
            }
            history_items.append(history_item)
        
        return history_items
        
    except Exception as e:
        print(f"履歴取得エラー (spaceId: {space_id}): {e}")
        return []

def lambda_handler(event, context):
    """
    API Gateway経由で呼び出されるLambda関数
    複数のspaceIdを受け取り、対応するデータと価格変更履歴をDynamoDBから取得して返す
    """
    try:
        # リクエストボディからspaceIdsを取得
        if event.get('body'):
            body = json.loads(event['body'])
        else:
            # テスト用にeventから直接取得
            body = event
        
        space_ids = body.get('spaceIds', [])
        history_limit = body.get('historyLimit', 10)  # 履歴取得件数（デフォルト10件）
        
        if not space_ids:
            return {
                'statusCode': 400,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'error': 'spaceIds parameter is required'
                })
            }
        
        # 複数のspaceIdに対してデータを取得
        results = []
        
        for space_id in space_ids:
            try:
                # OptionInfoからデータを取得
                response = info_table.get_item(
                    Key={
                        'spaceId': str(space_id)
                    }
                )
                
                if 'Item' in response:
                    item = response['Item']
                    
                    # optionsを整形
                    formatted_options = []
                    if 'options' in item:
                        for option in item['options']:
                            formatted_option = {
                                'name': option.get('name', ''),
                                'price': option.get('price', '')
                            }
                            formatted_options.append(formatted_option)
                    
                    # 価格変更履歴を取得
                    price_history = get_price_history(space_id, history_limit)
                    
                    # レスポンス用のデータを作成
                    result = {
                        'spaceId': item.get('spaceId'),
                        'name': item.get('name'),
                        'options': formatted_options,
                        'priceHistory': price_history,
                        'historyCount': len(price_history)
                    }
                    results.append(result)
                else:
                    # データが見つからない場合でも履歴は確認
                    price_history = get_price_history(space_id, history_limit)
                    
                    results.append({
                        'spaceId': str(space_id),
                        'error': 'Space not found in OptionInfo',
                        'priceHistory': price_history,
                        'historyCount': len(price_history)
                    })
                    
            except Exception as e:
                # 個別のエラーハンドリング
                results.append({
                    'spaceId': str(space_id),
                    'error': str(e),
                    'priceHistory': [],
                    'historyCount': 0
                })
        
        # 成功レスポンス
        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({
                'spaces': results,
                'totalSpaces': len(results),
                'requestedHistoryLimit': history_limit
            }, cls=DecimalEncoder, ensure_ascii=False)
        }
        
    except Exception as e:
        # エラーレスポンス
        return {
            'statusCode': 500,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({
                'error': str(e)
            })
        }

# バッチ取得版（より効率的）
def lambda_handler_batch(event, context):
    """
    BatchGetItemを使用した効率的なバージョン（履歴付き）
    """
    try:
        # リクエストボディからspaceIdsを取得
        if event.get('body'):
            body = json.loads(event['body'])
        else:
            body = event
        
        space_ids = body.get('spaceIds', [])
        history_limit = body.get('historyLimit', 10)
        
        if not space_ids:
            return {
                'statusCode': 400,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'error': 'spaceIds parameter is required'
                })
            }
        
        # DynamoDBクライアント（batch用）
        client = boto3.client('dynamodb')
        
        # BatchGetItem用のキーを準備
        keys = [{'spaceId': {'S': str(space_id)}} for space_id in space_ids]
        
        # バッチでOptionInfoデータを取得
        response = client.batch_get_item(
            RequestItems={
                'OptionInfo': {
                    'Keys': keys
                }
            }
        )
        
        results = []
        
        # 取得したOptionInfoデータを処理
        option_info_data = {}
        for item in response.get('Responses', {}).get('OptionInfo', []):
            space_id = item.get('spaceId', {}).get('S', '')
            
            formatted_options = []
            if 'options' in item and 'L' in item['options']:
                for option in item['options']['L']:
                    if 'M' in option:
                        option_data = option['M']
                        formatted_option = {
                            'name': option_data.get('name', {}).get('S', ''),
                            'price': option_data.get('price', {}).get('S', '')
                        }
                        formatted_options.append(formatted_option)
            
            option_info_data[space_id] = {
                'spaceId': space_id,
                'name': item.get('name', {}).get('S', ''),
                'options': formatted_options
            }
        
        # 各spaceIdに対して履歴を取得してレスポンスを構築
        for space_id in space_ids:
            str_space_id = str(space_id)
            
            # 価格変更履歴を取得
            price_history = get_price_history(str_space_id, history_limit)
            
            if str_space_id in option_info_data:
                # OptionInfoデータが存在する場合
                result = option_info_data[str_space_id]
                result['priceHistory'] = price_history
                result['historyCount'] = len(price_history)
                results.append(result)
            else:
                # OptionInfoデータが見つからない場合
                results.append({
                    'spaceId': str_space_id,
                    'error': 'Space not found in OptionInfo',
                    'priceHistory': price_history,
                    'historyCount': len(price_history)
                })
        
        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({
                'spaces': results,
                'totalSpaces': len(results),
                'requestedHistoryLimit': history_limit
            }, ensure_ascii=False)
        }
        
    except Exception as e:
        return {
            'statusCode': 500,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({
                'error': str(e)
            })
        }