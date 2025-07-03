import boto3
import json

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

    urls = body.get("urls", [])
    if not urls:
        return {
            'statusCode': 400,
            'body': json.dumps({'error': 'urls が不足しています'})
        }

    # SQSにメッセージ送信
    sqs = boto3.client('sqs')
    queue_url = 'https://sqs.ap-northeast-1.amazonaws.com/897729114300/CompetitorSales'

    try:
        # 5個ずつに分割して送信するよう改修
        for i in range(0, len(urls), 5):
            batch = urls[i:i + 5]
            sqs.send_message(
                QueueUrl=queue_url,
                MessageBody=json.dumps({
                    "urls": batch,
                    "timestamp": context.aws_request_id  # リクエストIDを追加
                })
            )

        response_body = {
            "message": f"{len(urls)}件のURL処理をキューに追加しました",
            "total_urls": len(urls),
            "status": "queued",
            "request_id": context.aws_request_id
        }

        return {
            'statusCode': 200,
            'body': json.dumps(response_body, ensure_ascii=False)
        }

    except Exception as e:
        return {
            'statusCode': 500,
            'body': json.dumps({
                'error': f"キューへの送信エラー: {str(e)}"
            })
        }
