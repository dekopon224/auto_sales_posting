/**
 * 毎朝実行トリガー用
 * ・スペースIDを３行おきに取得
 * ・APIコールして結果をキャッシュ
 * ・日付ヘッダー＆ドロップダウンをセット
 */
function updateSalesSheet() {
  const SHEET_NAME = '単価/売上';
  const API_URL = 'https://a776jppz94.execute-api.ap-northeast-1.amazonaws.com/prod/getcompetitorsales';
  
  try {
    const ss = SpreadsheetApp.getActiveSpreadsheet();
    const sh = ss.getSheetByName(SHEET_NAME);
    if (!sh) throw new Error(`シート"${SHEET_NAME}"が見つかりません`);

    // 1) スペースIDと出力先行のリスト作成 (2,5,8,... の行)
    const groups = [];
    for (let row = 2; ; row += 3) {
      const id = sh.getRange(row, 3).getDisplayValue().toString().trim();
      if (!id) break;
      groups.push({ spaceId: id, row });
    }
    
    if (groups.length === 0) {
      console.log('処理対象のスペースIDがありません');
      return;
    }

    // 2) API 一括リクエスト
    const payload = { queries: groups.map(g => ({ spaceId: g.spaceId })) };
    const res = UrlFetchApp.fetch(API_URL, {
      method: 'post',
      contentType: 'application/json',
      payload: JSON.stringify(payload),
      muteHttpExceptions: true
    });
    
    if (res.getResponseCode() !== 200) {
      throw new Error(`APIエラー(${res.getResponseCode()}): ${res.getContentText()}`);
    }
    
    const data = JSON.parse(res.getContentText());
    
    // レスポンスの検証
    if (!data.results || !Array.isArray(data.results)) {
      throw new Error('Invalid API response structure');
    }
    
    const results = data.results;

    // 3) 日付ヘッダー（1行目、O〜AB列に14日分）
    const startDate = new Date(data.period.start);
    const dateHeaders = [];
    for (let i = 0; i < 14; i++) {
      const d = new Date(startDate);
      d.setDate(d.getDate() + i);
      const txt = Utilities.formatDate(d, 'Asia/Tokyo', 'yyyy/MM/dd');
      sh.getRange(1, 15 + i).setValue(txt);
      dateHeaders.push(Utilities.formatDate(d, 'Asia/Tokyo', 'yyyy-MM-dd'));
    }

    // 4) キャッシュ用データ構築
    const cache = {};
    const errorSpaces = [];
    
    results.forEach((r, index) => {
      // エラーチェック
      if (r.error) {
        console.error(`Error for spaceId ${r.spaceId}: ${r.error}`);
        errorSpaces.push(r.spaceId);
        return;
      }
      
      const sid = r.spaceId;
      cache[sid] = cache[sid] || {};
      
      // プラン表示名を安全に取得
      let displayName = r.planId || 'Unknown';
      for (const day of r.daily_sales || []) {
        if (day.reservations && day.reservations.length > 0) {
          const planName = day.reservations[0].planDisplayName;
          if (planName) {
            displayName = planName;
            break;
          }
        }
      }
      
      // 重複チェック
      if (cache[sid][displayName]) {
        console.warn(`重複プラン検出: ${sid} - ${displayName}`);
        // プランIDを付加して一意にする
        displayName = `${displayName} (${r.planId})`;
      }
      
      // 売上データを保存
      cache[sid][displayName] = (r.daily_sales || []).map(d => ({
        date: d.date,
        sales: d.total_sales || 0
      }));
    });
    
    // キャッシュ保存（6時間）
    CacheService.getScriptCache().put('salesCache', JSON.stringify(cache), 6 * 60 * 60);
    // 日付ヘッダーも保存
    CacheService.getScriptCache().put('dateHeaders', JSON.stringify(dateHeaders), 6 * 60 * 60);

    // 5) 各グループのドロップダウン設定＋売上更新
    groups.forEach(({ spaceId, row }) => {
      const plans = Object.keys(cache[spaceId] || {});
      const rng = sh.getRange(row, 4, 3, 1);  // D列を3行まとめて
      
      // マージ状態のチェック
      if (!rng.isPartOfMerge()) {
        rng.merge();
      }
      
      // データバリデーションをクリア
      rng.clearDataValidations();
      
      // エラーがあったスペースの場合
      if (errorSpaces.includes(spaceId)) {
        sh.getRange(row, 4).setValue('エラー');
        sh.getRange(row, 15, 1, 14).clearContent();
        return;
      }

      // バリデーション再設定
      if (plans.length > 0) {
        const rule = SpreadsheetApp.newDataValidation()
          .requireValueInList(plans, true)
          .setAllowInvalid(false)
          .build();
        rng.setDataValidation(rule);
        
        // デフォルトで最初のプランを選択（未選択の場合）
        const currentValue = sh.getRange(row, 4).getValue().toString().trim();
        if (!currentValue) {
          sh.getRange(row, 4).setValue(plans[0]);
        }
      }

      // 選択されているプランの売上を表示
      const selectedPlan = sh.getRange(row, 4).getValue().toString().trim();
      if (selectedPlan && cache[spaceId] && cache[spaceId][selectedPlan]) {
        const salesArr = cache[spaceId][selectedPlan];
        const salesMap = {};
        salesArr.forEach(s => salesMap[s.date] = s.sales);
        
        // 日付に基づいて売上を設定
        for (let i = 0; i < 14; i++) {
          const dateKey = dateHeaders[i];
          const val = salesMap[dateKey] || 0;
          sh.getRange(row, 15 + i).setValue(val);
        }
      } else {
        // 選択なし or データなしならクリア
        sh.getRange(row, 15, 1, 14).clearContent();
      }
    });
    
    // 成功メッセージ
    console.log(`更新完了: ${groups.length}件のスペース, エラー: ${errorSpaces.length}件`);
    
  } catch (error) {
    console.error('updateSalesSheet error:', error);
    // 必要に応じて管理者に通知
    // MailApp.sendEmail('admin@example.com', 'GAS Error', error.toString());
  }
}

/**
 * ドロップダウン編集時に呼ばれるトリガー
 * D列(4) の 2,5,8...行だけをキャッチ
 * 選択プラン名に応じて O〜AB に 14日分の売上を表示
 */
function onEdit(e) {
  if (!e) return;
  
  const sheet = e.range.getSheet();
  if (sheet.getName() !== '単価/売上') return;

  const col = e.range.getColumn(), row = e.range.getRow();
  // D列 (4) の 2,5,8…行のみを対象
  if (col !== 4 || (row - 2) % 3 !== 0) return;

  const planName = e.range.getValue();
  if (!planName || planName === 'エラー') return;

  try {
    // キャッシュから読み出し
    const cacheRaw = CacheService.getScriptCache().get('salesCache');
    const dateHeadersRaw = CacheService.getScriptCache().get('dateHeaders');
    
    if (!cacheRaw) {
      console.error('キャッシュが見つかりません。updateSalesSheetを実行してください。');
      return;
    }
    
    const cache = JSON.parse(cacheRaw);
    const dateHeaders = dateHeadersRaw ? JSON.parse(dateHeadersRaw) : null;
    
    const spaceId = sheet.getRange(row, 3).getDisplayValue().toString().trim();
    const salesArr = (cache[spaceId] && cache[spaceId][planName]) || [];

    // 日付→売上 のマップ化
    const salesMap = {};
    salesArr.forEach(d => salesMap[d.date] = d.sales);

    if (dateHeaders) {
      // キャッシュされた日付ヘッダーを使用
      for (let i = 0; i < 14 && i < dateHeaders.length; i++) {
        const val = salesMap[dateHeaders[i]] || 0;
        sheet.getRange(row, 15 + i).setValue(val);
      }
    } else {
      // フォールバック：今日から14日分
      const today = new Date();
      for (let i = 0; i < 14; i++) {
        const d = new Date(today);
        d.setDate(d.getDate() + i);
        const key = Utilities.formatDate(d, 'Asia/Tokyo', 'yyyy-MM-dd');
        const val = salesMap[key] || 0;
        sheet.getRange(row, 15 + i).setValue(val);
      }
    }
  } catch (error) {
    console.error('onEdit error:', error);
  }
}