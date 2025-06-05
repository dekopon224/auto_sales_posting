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

    # 3) バッチ処理で全プラン×全日時の価格を一括取得
    plan_prices = _batch_fetch_prices_with_fallback(space_id, plan_ids, target_datetimes, day_type)

    # 4) プランごとに平均を計算
    result = {}
    for plan_id in plan_ids:
        prices = plan_prices.get(plan_id, [])
        # 該当プランの表示名（最初に見つかったものを使う）
        display_name = plan_names.get(plan_id, '')

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


def _batch_fetch_prices_with_fallback(space_id, plan_ids, target_datetimes, day_type):
    """
    全プラン×全日時の組み合わせについて、バッチ処理で価格を取得する。
    フォールバック処理も含めて一括で行い、プランごとの価格リストを返す。
    
    Returns:
        dict: {plan_id: [price1, price2, ...], ...}
    """
    # 1) 全候補キーを生成（直接取得 + 週単位フォールバック + 時間遡及フォールバック）
    all_keys = _generate_all_candidate_keys(plan_ids, target_datetimes)
    
    # 2) バッチで一括取得
    all_items = _batch_get_items_with_pagination(space_id, all_keys)
    
    # 3) 取得結果を整理（rate_key -> item のマッピング）
    items_map = {}
    for item in all_items:
        if item.get('day_type') == day_type:  # day_type フィルタリング
            items_map[item['rate_key']] = item
    
    # 4) プラン×日時ごとに最適な価格を選択
    plan_prices = {plan_id: [] for plan_id in plan_ids}
    
    for plan_id in plan_ids:
        for target_dt in target_datetimes:
            price = _find_best_price_from_candidates(plan_id, target_dt, items_map)
            if price is not None:
                plan_prices[plan_id].append(price)
    
    return plan_prices


def _generate_all_candidate_keys(plan_ids, target_datetimes):
    """
    全プラン×全日時について、フォールバック含む全候補のrate_keyを生成する。
    
    Returns:
        set: 重複除去されたrate_keyのセット
    """
    all_keys = set()
    
    for plan_id in plan_ids:
        for target_dt in target_datetimes:
            # 1) 直接取得
            direct_key = f"{target_dt}#{plan_id}"
            all_keys.add(direct_key)
            
            # 2) 週単位フォールバック（±1週間、±2週間）
            base_dt = datetime.strptime(target_dt, '%Y-%m-%dT%H:%M')
            for week_offset in [7, 14, -7, -14]:
                fallback_dt = base_dt + timedelta(days=week_offset)
                fallback_key = f"{fallback_dt.strftime('%Y-%m-%dT%H:00')}#{plan_id}"
                all_keys.add(fallback_key)
            
            # 3) 時間遡及フォールバック（最大24時間前まで）
            for hour_offset in range(1, 25):
                prev_dt = base_dt - timedelta(hours=hour_offset)
                prev_key = f"{prev_dt.strftime('%Y-%m-%dT%H:00')}#{plan_id}"
                all_keys.add(prev_key)
    
    return all_keys


def _batch_get_items_with_pagination(space_id, rate_keys):
    """
    batch_get_itemの100件制限に対応した分割処理で、全アイテムを取得する。
    
    Returns:
        list: 取得されたアイテムのリスト
    """
    all_items = []
    rate_keys_list = list(rate_keys)
    
    # 100件ずつに分割して処理
    for i in range(0, len(rate_keys_list), 100):
        batch_keys = rate_keys_list[i:i+100]
        
        # DynamoDB用のキー形式に変換
        request_items = {
            TABLE_NAME: {
                'Keys': [
                    {'spaceId': space_id, 'rate_key': rate_key}
                    for rate_key in batch_keys
                ]
            }
        }
        
        # UnprocessedKeysがある限り再試行
        while request_items:
            try:
                response = dynamodb.batch_get_item(RequestItems=request_items)
                
                # 取得結果を追加
                if TABLE_NAME in response.get('Responses', {}):
                    all_items.extend(response['Responses'][TABLE_NAME])
                
                # 未処理のキーがあれば次回のリクエストに設定
                request_items = response.get('UnprocessedKeys', {})
                
            except Exception as e:
                print(f"batch_get_item error: {e}")
                break  # エラーの場合は処理を中断
    
    return all_items


def _find_best_price_from_candidates(plan_id, target_dt, items_map):
    """
    指定されたプランと日時について、フォールバック優先順位に基づいて最適な価格を選択する。
    
    Returns:
        int or None: 見つかった価格、見つからない場合はNone
    """
    base_dt = datetime.strptime(target_dt, '%Y-%m-%dT%H:%M')
    
    # 優先順位1: 直接取得
    direct_key = f"{target_dt}#{plan_id}"
    if direct_key in items_map:
        return int(items_map[direct_key].get('price', 0))
    
    # 優先順位2: 週単位フォールバック
    for week_offset in [7, 14, -7, -14]:
        fallback_dt = base_dt + timedelta(days=week_offset)
        fallback_key = f"{fallback_dt.strftime('%Y-%m-%dT%H:00')}#{plan_id}"
        if fallback_key in items_map:
            return int(items_map[fallback_key].get('price', 0))
    
    # 優先順位3: 時間遡及フォールバック
    for hour_offset in range(1, 25):
        prev_dt = base_dt - timedelta(hours=hour_offset)
        prev_key = f"{prev_dt.strftime('%Y-%m-%dT%H:00')}#{plan_id}"
        if prev_key in items_map:
            return int(items_map[prev_key].get('price', 0))
    
    return None