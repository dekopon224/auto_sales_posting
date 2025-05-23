import json
import boto3
from boto3.dynamodb.conditions import Key
from decimal import Decimal

# DynamoDBクライアントの初期化
dynamodb = boto3.resource('dynamodb')
# テーブル名は環境変数で設定することを推奨
table = dynamodb.Table('OptionInfo')  # DynamoDBテーブル名

class DecimalEncoder(json.JSONEncoder):
    """DynamoDBのDecimal型をJSONでシリアライズするためのエンコーダー"""
    def default(self, obj):
        if isinstance(obj, Decimal):
            return int(obj)
        return super(DecimalEncoder, self).default(obj)

def lambda_handler(event, context):
    """
    API Gateway経由で呼び出されるLambda関数
    複数のspaceIdを受け取り、対応するデータをDynamoDBから取得して返す
    """
    try:
        # リクエストボディからspaceIdsを取得
        if event.get('body'):
            body = json.loads(event['body'])
        else:
            # テスト用にeventから直接取得
            body = event
        
        space_ids = body.get('spaceIds', [])
        
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
                # DynamoDBからデータを取得
                response = table.get_item(
                    Key={
                        'spaceId': str(space_id)  # spaceIdが文字列型の場合
                    }
                )
                
                if 'Item' in response:
                    item = response['Item']
                    
                    # optionsを整形
                    formatted_options = []
                    if 'options' in item:
                        for option in item['options']:
                            # boto3 resourceを使用した場合、型情報は自動変換される
                            formatted_option = {
                                'name': option.get('name', ''),
                                'price': option.get('price', '')
                            }
                            formatted_options.append(formatted_option)
                    
                    # レスポンス用のデータを作成
                    result = {
                        'spaceId': item.get('spaceId'),
                        'name': item.get('name'),
                        'options': formatted_options
                    }
                    results.append(result)
                else:
                    # データが見つからない場合
                    results.append({
                        'spaceId': str(space_id),
                        'error': 'Space not found'
                    })
                    
            except Exception as e:
                # 個別のエラーハンドリング
                results.append({
                    'spaceId': str(space_id),
                    'error': str(e)
                })
        
        # 成功レスポンス
        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({
                'spaces': results
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
    BatchGetItemを使用した効率的なバージョン
    """
    try:
        # リクエストボディからspaceIdsを取得
        if event.get('body'):
            body = json.loads(event['body'])
        else:
            body = event
        
        space_ids = body.get('spaceIds', [])
        
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
        
        # バッチでデータを取得
        response = client.batch_get_item(
            RequestItems={
                'OptionInfo': {  # DynamoDBテーブル名
                    'Keys': keys
                }
            }
        )
        
        results = []
        
        # 取得したデータを処理
        for item in response.get('Responses', {}).get('OptionInfo', []):
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
            
            result = {
                'spaceId': item.get('spaceId', {}).get('S', ''),
                'name': item.get('name', {}).get('S', ''),
                'options': formatted_options
            }
            results.append(result)
        
        # 見つからなかったspaceIdを特定
        found_ids = {r['spaceId'] for r in results}
        for space_id in space_ids:
            if str(space_id) not in found_ids:
                results.append({
                    'spaceId': str(space_id),
                    'error': 'Space not found'
                })
        
        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({
                'spaces': results
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