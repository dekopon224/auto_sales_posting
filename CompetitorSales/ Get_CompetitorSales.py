import boto3
import json
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from collections import defaultdict

# DynamoDB テーブル名
TABLE_NAME = 'CompetitorSales'

# JST タイムゾーン
JST = timezone(timedelta(hours=9))

def decimal_default(obj):
    """DynamoDBのDecimal型をJSONシリアライズ可能にする"""
    if isinstance(obj, Decimal):
        return int(obj)
    raise TypeError

def list_plan_ids(table, space_id):
    """
    spaceId に紐づく全アイテムを走査し、
    sortKey のプレフィックス（planId 部分）だけを抽出して返す
    """
    plan_ids = set()
    response = table.query(
        KeyConditionExpression='spaceId = :space_id',
        ExpressionAttributeValues={':space_id': space_id}
    )
    items = response.get('Items', [])
    while 'LastEvaluatedKey' in response:
        response = table.query(
            KeyConditionExpression='spaceId = :space_id',
            ExpressionAttributeValues={':space_id': space_id},
            ExclusiveStartKey=response['LastEvaluatedKey']
        )
        items.extend(response.get('Items', []))

    for itm in items:
        sk = itm.get('sortKey', '')
        # sortKey が "planId#..." の形式なら split で planId を取り出す
        if '#' in sk:
            plan_id = sk.split('#', 1)[0]
            plan_ids.add(plan_id)
    return list(plan_ids)

def get_sales_data(table, space_id, plan_id, start_date, end_date):
    """
    特定の spaceId と planId の売上データを取得し、日ごとに集計する
    同じ予約スロットが複数ある場合は、processed_at が最新のものを使用
    """
    try:
        # DynamoDBからデータを取得
        response = table.query(
            KeyConditionExpression='spaceId = :space_id AND begins_with(sortKey, :plan_prefix)',
            ExpressionAttributeValues={
                ':space_id': space_id,
                ':plan_prefix': f'{plan_id}#'
            }
        )
        items = response.get('Items', [])
        while 'LastEvaluatedKey' in response:
            response = table.query(
                KeyConditionExpression='spaceId = :space_id AND begins_with(sortKey, :plan_prefix)',
                ExpressionAttributeValues={
                    ':space_id': space_id,
                    ':plan_prefix': f'{plan_id}#'
                },
                ExclusiveStartKey=response['LastEvaluatedKey']
            )
            items.extend(response.get('Items', []))

        # 各予約スロットの最新データを保持する辞書
        latest_reservations = {}
        
        for item in items:
            reservation_date = item.get('reservationDate', '')
            start_time = item.get('start_time', '')
            processed_at = item.get('processed_at', '')
            
            if not reservation_date or not start_time:
                continue
                
            # ユニークキー（日付+開始時間）
            reservation_key = f"{reservation_date}#{start_time}"
            
            # 既存のエントリがない、またはより新しいデータの場合は更新
            if reservation_key not in latest_reservations:
                latest_reservations[reservation_key] = item
            else:
                existing_processed_at = latest_reservations[reservation_key].get('processed_at', '')
                if processed_at > existing_processed_at:
                    latest_reservations[reservation_key] = item

        # 日ごとに集計（最新データのみを使用）
        daily_sales = defaultdict(lambda: {
            'date': '',
            'total_sales': 0,
            'reservation_count': 0,
            'reservations': []
        })

        for item in latest_reservations.values():
            reservation_date = item.get('reservationDate', '')
            try:
                res_date = datetime.strptime(reservation_date, '%Y-%m-%d').date()
            except:
                continue
            if res_date < start_date or res_date > end_date:
                continue

            date_str = reservation_date
            daily_sales[date_str]['date'] = date_str
            daily_sales[date_str]['total_sales'] += int(item.get('price', 0))
            daily_sales[date_str]['reservation_count'] += 1
            daily_sales[date_str]['reservations'].append({
                'start_time': item.get('start_time', ''),
                'end_time': item.get('end_time', ''),
                'price': int(item.get('price', 0)),
                'planDisplayName': item.get('planDisplayName', ''),
                'processed_at': item.get('processed_at', '')  # デバッグ用
            })

        sorted_sales = sorted(daily_sales.values(), key=lambda x: x['date'])
        total_sales = sum(day['total_sales'] for day in sorted_sales)
        total_reservations = sum(day['reservation_count'] for day in sorted_sales)

        return {
            'success': True,
            'spaceId': space_id,
            'planId': plan_id,
            'summary': {
                'total_sales': total_sales,
                'total_reservations': total_reservations,
                'average_daily_sales': total_sales / 15 if total_sales > 0 else 0
            },
            'daily_sales': sorted_sales
        }

    except Exception as e:
        return {
            'success': False,
            'spaceId': space_id,
            'planId': plan_id,
            'error': str(e)
        }

def lambda_handler(event, context):
    """
    spaceId（と任意の planId）を受け取り、
    今日から2週間先までの売上をプラン単位でまとめて返す
    """
    # リクエストボディの解析
    try:
        if 'body' not in event or not event['body']:
            raise ValueError('リクエストボディが必要です')
        body = json.loads(event['body'])
        if 'queries' in body and isinstance(body['queries'], list):
            queries = body['queries']
        elif 'spaceId' in body:
            # 後方互換：planId 指定があればそれを使い、なければ全プランを取る
            queries = [{'spaceId': body['spaceId'], 'planId': body.get('planId', '')}]
        else:
            raise ValueError('spaceId と planId のペア、または queries リストが必要です')

        # バリデーション
        for i, q in enumerate(queries):
            if not q.get('spaceId'):
                raise ValueError(f'queries[{i}] に spaceId が必要です')
    except Exception as e:
        return {
            'statusCode': 400,
            'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
            'body': json.dumps({'error': str(e)}, ensure_ascii=False)
        }

    # DynamoDB テーブル参照
    dynamodb = boto3.resource('dynamodb')
    table = dynamodb.Table(TABLE_NAME)

    # 期間：今日から2週間先
    now_jst = datetime.now(JST)
    start_date = now_jst.date()
    end_date = start_date + timedelta(days=14)

    results = []
    successful_count = 0
    failed_count = 0

    for query in queries:
        space_id = query['spaceId']
        # planId 未指定なら自動取得
        if query.get('planId'):
            plan_list = [query['planId']]
        else:
            plan_list = list_plan_ids(table, space_id)

        for plan_id in plan_list:
            res = get_sales_data(table, space_id, plan_id, start_date, end_date)
            if res.get('success'):
                successful_count += 1
                del res['success']
            else:
                failed_count += 1
            results.append(res)

    # レスポンス組み立て
    response_body = {
        'period': {'start': start_date.isoformat(), 'end': end_date.isoformat()},
        'summary': {'total_queries': len(results), 'successful': successful_count, 'failed': failed_count},
        'results': results,
        'timestamp': now_jst.isoformat()
    }

    # 単一クエリ＆エラーなしなら従来形式で返す
    if len(results) == 1 and 'error' not in results[0]:
        r = results[0]
        response_body = {
            'spaceId': r['spaceId'],
            'planId': r['planId'],
            'period': response_body['period'],
            'summary': r['summary'],
            'daily_sales': r['daily_sales'],
            'timestamp': response_body['timestamp']
        }

    return {
        'statusCode': 200,
        'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
        'body': json.dumps(response_body, ensure_ascii=False, default=decimal_default)
    }
