import json
import boto3
import os
from datetime import datetime, timedelta

def lambda_handler(event, context):
    """
    GASからのリクエストを受けてジョブを分割
    毎回、全URL × 6期間（3ヶ月分）のジョブを生成
    """
    
    # URLリストの取得
    urls = []
    
    # API Gatewayからの場合（GAS経由）
    if 'body' in event:
        try:
            body = json.loads(event['body'])
            urls = body.get('urls', [])
        except json.JSONDecodeError:
            return {
                'statusCode': 400,
                'body': json.dumps({'error': 'Invalid JSON in request body'})
            }
    # 直接呼び出しの場合（テスト用）
    elif 'urls' in event:
        urls = event['urls']
    
    if not urls or not isinstance(urls, list):
        return {
            'statusCode': 400,
            'body': json.dumps({'error': 'URLリストが指定されていません'})
        }
    
    # 固定の期間分割設定（3ヶ月を2週間ごとに6分割）
    job_configs = [
        {"offset_days": 0, "scan_days": 14},    # 今日から2週間
        {"offset_days": 14, "scan_days": 14},   # 2週間後から2週間
        {"offset_days": 28, "scan_days": 14},   # 4週間後から2週間
        {"offset_days": 42, "scan_days": 14},   # 6週間後から2週間
        {"offset_days": 56, "scan_days": 14},   # 8週間後から2週間
        {"offset_days": 70, "scan_days": 14},   # 10週間後から2週間
    ]
    
    # SQSクライアント
    sqs = boto3.client('sqs')
    queue_url = os.environ['SQS_QUEUE_URL']
    
    # ジョブカウンター
    total_jobs = 0
    
    # 各URLに対して6つのジョブを作成
    for url in urls:
        for config in job_configs:
            message = {
                "urls": [url],
                "offset_days": config["offset_days"],
                "scan_days": config["scan_days"],
                "execution_time": datetime.now().isoformat()
            }
            
            # SQSにメッセージ送信
            try:
                sqs.send_message(
                    QueueUrl=queue_url,
                    MessageBody=json.dumps(message)
                )
                total_jobs += 1
            except Exception as e:
                print(f"SQS送信エラー: {url} - {e}")
    
    # 実行ログ
    print(f"ジョブ生成完了: {len(urls)}個のURL × 6期間 = {total_jobs}ジョブ")
    
    return {
        'statusCode': 200,
        'body': json.dumps({
            'message': f'{total_jobs}個のジョブを生成しました',
            'urls_count': len(urls),
            'periods': 6,
            'total_jobs': total_jobs
        }, ensure_ascii=False)
    }