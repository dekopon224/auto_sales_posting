import os
import json
from decimal import Decimal
from datetime import datetime, timedelta
import boto3
from boto3.dynamodb.conditions import Key

# 環境変数から DynamoDB のテーブル名を取得
TABLE_NAME = os.environ.get('TABLE_NAME', 'SpaceRate')

# boto3 の DynamoDB テーブルオブジェクトを生成
dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table(TABLE_NAME)


def lambda_handler(event, context):
    """
    Lambda エントリポイント。
    リクエストボディとして JSON を想定し、以下のキーを受け取る：
      - spaceId:      対象スペース ID (文字列)
      - start_date:   取得開始日 (YYYY-MM-DD)
      - end_date:     取得終了日 (YYYY-MM-DD)
      - start_hour:   時間帯開始 (整数、0-23)
      - end_hour:     時間帯終了 (整数、0-23: 
                       入力例) start_hour=9, end_hour=17 なら 9:00〜17:00 をすべて含める
      - day_type:     'weekday' または 'weekend'
    戻り値として、プランごとに平均単価を返す。
    """

    try:
        body = _parse_event_body(event)
        space_id   = body['spaceId']
        start_date = datetime.strptime(body['start_date'], '%Y-%m-%d').date()
        end_date   = datetime.strptime(body['end_date'], '%Y-%m-%d').date()
        start_hour = int(body['start_hour'])
        end_hour   = int(body['end_hour'])
        day_type   = body['day_type']
    except Exception as e:
        return {
            'statusCode': 400,
            'body': json.dumps({'error': f'リクエストパラメータ不正: {str(e)}'}, ensure_ascii=False)
        }

    # 1) 期間内に存在するプラン ID をあらかじめ収集しておく（DynamoDB 全件スキャン→Query でも可）
    plan_ids, plan_names = _collect_all_plans_for_space(space_id)

    # 2) 取得対象となる日時（YYYY-MM-DDThh:00）の一覧を作成
    target_datetimes = _generate_target_datetimes(start_date, end_date, start_hour, end_hour)

    # 3) プランごとに価格を取得し、リストに格納して平均を計算
    result = {}
    for plan_id in plan_ids:
        prices = []
        # 該当プランの表示名（最初に見つかったものを使う）
        display_name = plan_names.get(plan_id, '')

        for dt in target_datetimes:
            price = _fetch_price_with_fallback(
                space_id=space_id,
                plan_id=plan_id,
                target_dt=dt,
                day_type=day_type
            )
            if price is not None:
                prices.append(price)

        if prices:
            avg_price = float(sum(prices) / len(prices))
        else:
            avg_price = None

        result[plan_id] = {
            'planDisplayName': display_name,
            'average_price': avg_price,
            'samples_count': len(prices)
        }

    return {
        'statusCode': 200,
        'body': json.dumps(
            {'spaceId': space_id, 'start_date': str(start_date), 'end_date': str(end_date),
             'day_type': day_type, 'plans': result},
            ensure_ascii=False
        )
    }


def _parse_event_body(event):
    """
    HTTP API 形式を想定し、event['body'] から JSON を取得するユーティリティ。
    SQS トリガーなどの場合は event が異なる形になるため、必要に応じて拡張可。
    """
    if 'body' in event:
        try:
            return json.loads(event['body'])
        except:
            raise ValueError('body が JSON にパースできません')
    else:
        # SQS や他の形式の場合は event そのものを JSON として扱う想定
        return event


def _collect_all_plans_for_space(space_id):
    """
    指定した SpaceID について DynamoDB を Query し、現状登録されている planId と planDisplayName を収集する。
    DynamoDB のパーティションキーが 'spaceId'、ソートキーが 'rate_key' である前提。
    Query を使って、ProjectionExpression で planId と planDisplayName のみを取得し、重複を除去。
    """
    plan_ids = set()
    plan_names = {}

    # Query で全アイテムを取得する。必要に応じて FilterExpression を入れて絞り込み可。
    # ただし、Query のままだと期間指定がないので、全件取得 → for で planId を collect する実装
    exclusive_start_key = None
    while True:
        if exclusive_start_key:
            resp = table.query(
                KeyConditionExpression=Key('spaceId').eq(space_id),
                ProjectionExpression='planId, planDisplayName, rate_key',
                ExclusiveStartKey=exclusive_start_key
            )
        else:
            resp = table.query(
                KeyConditionExpression=Key('spaceId').eq(space_id),
                ProjectionExpression='planId, planDisplayName, rate_key'
            )

        for item in resp.get('Items', []):
            pid = item.get('planId')
            if pid:
                plan_ids.add(pid)
                # 最初に見つかった表示名をセット
                if pid not in plan_names and 'planDisplayName' in item:
                    plan_names[pid] = item['planDisplayName']

        exclusive_start_key = resp.get('LastEvaluatedKey')
        if not exclusive_start_key:
            break

    return list(plan_ids), plan_names


def _generate_target_datetimes(start_date, end_date, start_hour, end_hour):
    """
    start_date〜end_date の各日について、start_hour 〜 end_hour の間のそれぞれの時刻文字列 'YYYY-MM-DDThh:00' を返す。
    例）2025-06-01 ～ 2025-06-03、start_hour=9、end_hour=11 の場合、
      ['2025-06-01T09:00', '2025-06-01T10:00', '2025-06-01T11:00',
       '2025-06-02T09:00', ...]
    """
    target_datetimes = []
    current = start_date
    while current <= end_date:
        for hour in range(start_hour, end_hour + 1):
            target_datetimes.append(f"{current.isoformat()}T{hour:02d}:00")
        current = current + timedelta(days=1)
    return target_datetimes


def _fetch_price_with_fallback(space_id, plan_id, target_dt, day_type):
    """
    指定の日時 target_dt（文字列 'YYYY-MM-DDThh:00'）と plan_id、day_type をもとに、
    1) 直接取得
    2) ±1 週間、±2 週間ずらして同時刻を取得
    3) それでも無ければ「直前１時間」を再帰的に探す
    を順に試みて価格 (int) を返す。見つからなければ None を返す。
    """
    # ステップ 1) 直接取得
    found = _try_get_item(space_id, plan_id, target_dt, day_type)
    if found is not None:
        return found

    # ステップ 2) 先週・先々週・来週・再来週
    base_dt = datetime.strptime(target_dt, '%Y-%m-%dT%H:%M')
    for week_offset in [7, 14, -7, -14]:
        fallback_dt = base_dt + timedelta(days=week_offset)
        fallback_key = fallback_dt.strftime('%Y-%m-%dT%H:00')
        found = _try_get_item(space_id, plan_id, fallback_key, day_type)
        if found is not None:
            return found

    # ステップ 3) 「直前１時間」を再帰的に探す
    return _fetch_previous_hour_price(space_id, plan_id, base_dt, day_type, max_hours=24)


def _try_get_item(space_id, plan_id, dt_key, day_type):
    """
    DynamoDB からキー (spaceId, rate_key=dt_key#plan_id) で item を取得し、day_type が合っていれば price を返す。
    該当なしや day_type 不整合の場合は None を返す。
    """
    rate_key = f"{dt_key}#{plan_id}"
    try:
        resp = table.get_item(Key={'spaceId': space_id, 'rate_key': rate_key})
        item = resp.get('Item')
        if not item:
            return None

        # day_type が一致しなければ None (「平日か週末か」は厳密に指定)
        if item.get('day_type') != day_type:
            return None

        return int(item.get('price', 0))
    except Exception:
        return None


def _fetch_previous_hour_price(space_id, plan_id, dt_obj, day_type, max_hours=24):
    """
    target_dt（datetime オブジェクト）の「1時間前、2時間前、...」とさかのぼって
    _try_get_item が見つかるまで再帰的に探索。最大 max_hours だけさかのぼる。
    見つかれば price を返し、最後まで見つからなければ None。
    """
    if max_hours <= 0:
        return None

    # １時間前を計算
    prev_dt = dt_obj - timedelta(hours=1)
    prev_key = prev_dt.strftime('%Y-%m-%dT%H:00')
    found = _try_get_item(space_id, plan_id, prev_key, day_type)
    if found is not None:
        return found
    else:
        return _fetch_previous_hour_price(space_id, plan_id, prev_dt, day_type, max_hours - 1)
