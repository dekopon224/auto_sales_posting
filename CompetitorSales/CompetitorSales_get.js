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

    // 3) 日付ヘッダーの構築（O列から開始）
    // ヘッダーが既に設定されているかチェック
    if (sh.getRange(1, 15).getValue() !== '2025年合計') {
      setupDateHeaders(sh);
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
        sales: d.total_sales || 0,
        reservations: d.reservations || []
      }));
    });
    
    // キャッシュ保存（6時間）
    CacheService.getScriptCache().put('salesCache', JSON.stringify(cache), 6 * 60 * 60);

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
        // 年合計・月合計のセルに数式を設定
        setTotalFormulas(sh, row);
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
        updateSalesData(sh, row, cache[spaceId][selectedPlan]);
      }
      
      // 年合計・月合計の数式を設定
      setTotalFormulas(sh, row);
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
 * 日付ヘッダーを設定する関数（修正版）
 * 日付を確実に文字列として設定
 */
function setupDateHeaders(sheet) {
  const startCol = 15; // O列
  let col = startCol;
  
  // O列: 2025年合計
  sheet.getRange(1, col).setValue('2025年合計');
  col++;
  
  // 今日の日付を取得
  const today = new Date();
  const currentMonth = today.getMonth() + 1; // 0ベースなので+1
  const currentDay = today.getDate();
  
  // 2025年6月から12月までのヘッダーを作成
  for (let month = 6; month <= 12; month++) {
    // 月合計列
    sheet.getRange(1, col).setValue(`${month}月合計`);
    col++;
    
    // 該当月の日数を取得
    const daysInMonth = new Date(2025, month, 0).getDate();
    
    // 日毎のヘッダー
    const startDay = (month === 6) ? 11 : 1; // 6月は11日から開始
    for (let day = startDay; day <= daysInMonth; day++) {
      const dateStr = `2025/${String(month).padStart(2, '0')}/${String(day).padStart(2, '0')}`;
      // 明示的に文字列として設定
      sheet.getRange(1, col).setValue(dateStr.toString());
      col++;
    }
  }
}

/**
 * ヘッダーを強制的に文字列に修正する関数
 * 既存の日付オブジェクトを文字列に変換
 */
function fixDateHeaders() {
  const SHEET_NAME = '単価/売上';
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sh = ss.getSheetByName(SHEET_NAME);
  
  const startCol = 15; // O列
  const lastCol = sh.getLastColumn();
  
  for (let col = startCol; col <= lastCol; col++) {
    const header = sh.getRange(1, col).getValue();
    
    // 日付オブジェクトの場合、文字列に変換
    if (header instanceof Date) {
      const year = header.getFullYear();
      const month = String(header.getMonth() + 1).padStart(2, '0');
      const day = String(header.getDate()).padStart(2, '0');
      const dateStr = `${year}/${month}/${day}`;
      sh.getRange(1, col).setValue(dateStr);
      console.log(`Fixed header at col ${col}: ${dateStr}`);
    }
  }
}

/**
 * 売上データを更新する関数（期間考慮版）
 * APIの取得期間内のみ0円表示、期間外は空欄
 * N列のチェックボックスがTRUEの場合、朝6時〜11時の予約を除外
 */
function updateSalesData(sheet, row, salesData) {
  const startCol = 15; // O列から開始
  
  // N列（14列）のチェックボックスの状態を確認
  const excludeMorning = sheet.getRange(row, 14).getValue() === true;
  
  // 売上データを日付→売上のマップに変換
  const salesMap = {};
  let minDate = null;
  let maxDate = null;
  
  salesData.forEach(item => {
    let totalSales = item.sales || 0;
    
    // チェックボックスがTRUEの場合、朝6時〜11時の予約を除外
    if (excludeMorning && item.reservations && item.reservations.length > 0) {
      totalSales = 0;
      item.reservations.forEach(reservation => {
        const startTime = reservation.start_time;
        // 開始時間が6:00以降かつ11:00より前の場合は除外
        if (!isInMorningRange(startTime)) {
          totalSales += reservation.price || 0;
        }
      });
    }
    
    salesMap[item.date] = totalSales;
    // 最小・最大日付を記録
    if (!minDate || item.date < minDate) minDate = item.date;
    if (!maxDate || item.date > maxDate) maxDate = item.date;
  });
  
  // デバッグ用：どの日付のデータがあるか確認
  console.log(`Row ${row} - Available dates:`, Object.keys(salesMap).sort());
  console.log(`Row ${row} - Period: ${minDate} to ${maxDate}`);
  console.log(`Row ${row} - Exclude morning: ${excludeMorning}`);
  
  // ヘッダー行から日付を読み取り、対応する売上を設定
  let col = startCol + 1; // P列から開始（O列は年合計なのでスキップ）
  
  for (let month = 6; month <= 12; month++) {
    // 月合計列は既にcolが指している
    const monthTotalCol = col;
    col++; // 月合計列をスキップして、その月の最初の日付列へ
    
    const daysInMonth = new Date(2025, month, 0).getDate();
    const startDay = (month === 6) ? 11 : 1; // 6月は11日から開始
    
    for (let day = startDay; day <= daysInMonth; day++) {
      const dateKey = `2025-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
      const header = sheet.getRange(1, col).getValue();
      
      // ヘッダーが日付かどうかを判定（日付オブジェクトまたは日付文字列）
      let isDateHeader = false;
      
      if (header) {
        // 日付オブジェクトの場合
        if (header instanceof Date) {
          isDateHeader = true;
        }
        // 文字列で日付形式の場合（YYYY/MM/DD）
        else if (typeof header === 'string' && header.match(/^\d{4}\/\d{2}\/\d{2}$/)) {
          isDateHeader = true;
        }
        // 日付オブジェクトのtoString()形式の場合
        else if (header.toString().includes('GMT')) {
          isDateHeader = true;
        }
      }
      
      // デバッグ用：ヘッダーと日付キーの対応を確認
      if (month === 7 && day >= 6 && day <= 10) {
        console.log(`Col ${col}, DateKey: ${dateKey}, Has data: ${salesMap.hasOwnProperty(dateKey)}, IsDateHeader: ${isDateHeader}`);
      }
      
      if (isDateHeader) {
        // 日付がAPIの取得期間内かチェック
        if (minDate && maxDate && dateKey >= minDate && dateKey <= maxDate) {
          // 期間内の場合：データがあればその値を、なければ0を設定
          const value = salesMap.hasOwnProperty(dateKey) ? salesMap[dateKey] : 0;
          sheet.getRange(row, col).setValue(value);
        } else if (salesMap.hasOwnProperty(dateKey)) {
          // 期間外でもデータがある場合は設定（念のため）
          sheet.getRange(row, col).setValue(salesMap[dateKey]);
        }
        // それ以外（期間外でデータなし）は何もしない（空欄のまま）
      }
      col++;
    }
  }
}

/**
 * 時刻が朝6時〜11時の範囲内かを判定する関数
 * @param {string} timeStr - "HH:MM"形式の時刻文字列
 * @return {boolean} - 6:00〜10:59の範囲内ならtrue
 */
function isInMorningRange(timeStr) {
  if (!timeStr || typeof timeStr !== 'string') return false;
  
  const [hours, minutes] = timeStr.split(':').map(Number);
  const timeInMinutes = hours * 60 + minutes;
  
  // 6:00は360分、11:00は660分
  return timeInMinutes >= 360 && timeInMinutes < 660;
}

/**
 * 年合計・月合計の数式を設定する関数
 */
function setTotalFormulas(sheet, row) {
  const startCol = 15; // O列
  
  // O列: 2025年合計の数式
  const yearFormula = createYearTotalFormula(row);
  sheet.getRange(row, startCol).setFormula(yearFormula);
  
  // 各月の合計数式を設定
  let col = startCol + 1; // P列から
  for (let month = 6; month <= 12; month++) {
    const monthFormula = createMonthTotalFormula(row, month);
    sheet.getRange(row, col).setFormula(monthFormula);
    
    // 次の月合計列の位置を計算
    const daysInMonth = new Date(2025, month, 0).getDate();
    const startDay = (month === 6) ? 11 : 1; // 6月は11日から
    const actualDays = daysInMonth - startDay + 1;
    col += actualDays + 1; // ← 実際の日数を使用
  }
}

/**
 * 年合計の数式を作成
 */
function createYearTotalFormula(row) {
  const ranges = [];
  let col = 17; // Q列から開始（6月11日）
  
  for (let month = 6; month <= 12; month++) {
    const daysInMonth = new Date(2025, month, 0).getDate();
    const startDay = (month === 6) ? 11 : 1; // 6月は11日から
    const actualDays = daysInMonth - startDay + 1;
    const startColLetter = columnToLetter(col);
    const endColLetter = columnToLetter(col + actualDays - 1);
    ranges.push(`${startColLetter}${row}:${endColLetter}${row}`);
    col += actualDays + 1; // 実際の日数 + 次の月合計列
  }
  
  return `=SUM(${ranges.join(',')})`;
}


/**
 * 月合計の数式を作成
 */
function createMonthTotalFormula(row, month) {
  let col = 17; // Q列から開始
  
  // 指定月の開始列を見つける
  for (let m = 6; m < month; m++) {
    const daysInMonth = new Date(2025, m, 0).getDate();
    const startDay = (m === 6) ? 11 : 1; // 6月は11日から
    const actualDays = daysInMonth - startDay + 1;
    col += actualDays + 1;
  }
  
  const daysInMonth = new Date(2025, month, 0).getDate();
  const startDay = (month === 6) ? 11 : 1; // 6月は11日から
  const actualDays = daysInMonth - startDay + 1;
  const startColLetter = columnToLetter(col);
  const endColLetter = columnToLetter(col + actualDays - 1);
  
  return `=SUM(${startColLetter}${row}:${endColLetter}${row})`;
}

/**
 * 列番号をアルファベットに変換
 */
function columnToLetter(column) {
  let temp, letter = '';
  while (column > 0) {
    temp = (column - 1) % 26;
    letter = String.fromCharCode(temp + 65) + letter;
    column = (column - temp - 1) / 26;
  }
  return letter;
}

/**
 * ドロップダウン編集時に呼ばれるトリガー
 * D列(4) の 2,5,8...行だけをキャッチ
 * 選択プラン名に応じて該当日付に売上を表示
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
    
    if (!cacheRaw) {
      console.error('キャッシュが見つかりません。updateSalesSheetを実行してください。');
      return;
    }
    
    const cache = JSON.parse(cacheRaw);
    
    const spaceId = sheet.getRange(row, 3).getDisplayValue().toString().trim();
    const salesArr = (cache[spaceId] && cache[spaceId][planName]) || [];

    // 売上データを更新
    updateSalesData(sheet, row, salesArr);
    
    // 年合計・月合計の数式を設定（念のため）
    setTotalFormulas(sheet, row);
    
  } catch (error) {
    console.error('onEdit error:', error);
  }
}

// 初回セットアップ用（手動実行）
function initialSetup() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sh = ss.getSheetByName('単価/売上');
  setupDateHeaders(sh);
}