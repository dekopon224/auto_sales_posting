/**
 * 毎朝実行トリガー用
 * ・スペースIDを３行おきに取得
 * ・APIコールして結果をキャッシュ
 * ・日付ヘッダー＆ドロップダウンをセット
 */
function updateSalesSheet() {
  const SHEET_NAME = '単価/売上';
  const API_URL    = 'https://a776jppz94.execute-api.ap-northeast-1.amazonaws.com/prod/getcompetitorsales';
  const ss  = SpreadsheetApp.getActiveSpreadsheet();
  const sh  = ss.getSheetByName(SHEET_NAME);
  if (!sh) throw new Error(`シート"${SHEET_NAME}"が見つかりません`);

  // 1) スペースIDと出力先行のリスト作成 (2,5,8,... の行)
  const groups = [];
  for (let row = 2; ; row += 3) {
    const id = sh.getRange(row, 3).getDisplayValue().toString().trim();
    if (!id) break;
    groups.push({ spaceId: id, row });
  }
  if (groups.length === 0) return;

  // 2) API 一括リクエスト
  const payload = { queries: groups.map(g => ({ spaceId: g.spaceId })) };
  const res = UrlFetchApp.fetch(API_URL, {
    method: 'post',
    contentType: 'application/json',
    payload: JSON.stringify(payload),
    muteHttpExceptions: true
  });
  if (res.getResponseCode() !== 200) {
    console.error('APIエラー:', res.getContentText());
    return;
  }
  const data = JSON.parse(res.getContentText());
  const results = data.results;

  // 3) 日付ヘッダー（1行目、O〜AB列に14日分）
  const startDate = new Date(data.period.start);
  for (let i = 0; i < 14; i++) {
    const d = new Date(startDate);
    d.setDate(d.getDate() + i);
    const txt = Utilities.formatDate(d, 'Asia/Tokyo', 'yyyy/MM/dd');
    sh.getRange(1, 15 + i).setValue(txt);
  }

  // 4) キャッシュ用データ構築
  const cache = {};
  results.forEach(r => {
    const sid = r.spaceId;
    const dn  = (r.daily_sales[0] && r.daily_sales[0].reservations[0].planDisplayName)
              || r.planId;
    cache[sid] = cache[sid] || {};
    cache[sid][dn] = r.daily_sales.map(d => ({
      date:  d.date,
      sales: d.total_sales
    }));
  });
  CacheService.getScriptCache().put('salesCache', JSON.stringify(cache), 6 * 60 * 60);

  // 5) 各グループのドロップダウン設定＋売上クリア or 再描画
  groups.forEach(({ spaceId, row }) => {
    const plans = Object.keys(cache[spaceId] || []);
    const rng   = sh.getRange(row, 4, 3, 1);  // D列を3行まとめて
    rng.merge();
    // クリアは「コンテンツ（売上セルのみ）」「旧バリデーション」のみ
    rng.clearDataValidations();
    // D列セル自体は消さずに残すので clearContent は行わない

    // バリデーション再設定
    if (plans.length) {
      const rule = SpreadsheetApp.newDataValidation()
        .requireValueInList(plans, true)
        .setAllowInvalid(false)
        .build();
      rng.setDataValidation(rule);
    }

    // ①D列にすでにプラン選択があるかチェック
    const selectedPlan = sh.getRange(row, 4).getValue().toString().trim();
    if (selectedPlan && cache[spaceId] && cache[spaceId][selectedPlan]) {
      // ②売上セル(O〜AB)に再描画
      const salesArr = cache[spaceId][selectedPlan];
      for (let i = 0; i < 14; i++) {
        const val = (salesArr[i] && salesArr[i].sales) || 0;
        sh.getRange(row, 15 + i).setValue(val);
      }
    } else {
      // 選択なし or キャッシュなしなら従来どおりクリア
      sh.getRange(row, 15, 1, 14).clearContent();
    }
  });
}

/**
 * ドロップダウン編集時に呼ばれるトリガー
 * D列(4) の 2,5,8...行だけをキャッチ
 * 選択プラン名に応じて O〜AB に 14日分の売上を表示
 */
function onEdit(e) {
  const sheet = e.range.getSheet();
  if (sheet.getName() !== '単価/売上') return;

  const col = e.range.getColumn(), row = e.range.getRow();
  // D列 (4) の 2,5,8…行のみを対象
  if (col !== 4 || (row - 2) % 3 !== 0) return;

  const planName = e.range.getValue();
  if (!planName) return;

  // キャッシュから読み出し
  const cacheRaw = CacheService.getScriptCache().get('salesCache');
  const cache = cacheRaw ? JSON.parse(cacheRaw) : {};
  const spaceId = sheet.getRange(row, 3).getDisplayValue().toString().trim();
  const salesArr = (cache[spaceId] && cache[spaceId][planName]) || [];

  // 日付→売上 のマップ化
  const m = {};
  salesArr.forEach(d => m[d.date] = d.sales);

  // 今日から14日分を埋める
  const today = new Date();
  for (let i = 0; i < 14; i++) {
    const d = new Date(today);
    d.setDate(d.getDate() + i);
    // ↓ 引数を (date, timeZone, format) の順に
    const key = Utilities.formatDate(d, 'Asia/Tokyo', 'yyyy-MM-dd');
    const val = m[key] || 0;
    sheet.getRange(row, 15 + i).setValue(val);
  }
}
