// ============ 定数定義 ============
const SPREADSHEET_ID = '1YLt2IWtMPjkD9oi7XaF3scInkiffshv1SYnEjlbqoCo';
const SHEET_NAME = '単価/売上';
const TEMP_SHEET_NAME = '_temp_data';

// 一時シートのセル位置を定数で管理
const TEMP_CELLS = {
  BATCHES: 'A1',
  BATCH_INDEX: 'B1',
  FINALIZE_INDEX: 'B2',
  PLAN_MAPPING: 'C1',
  SPACE_DATA_START: 'A2' // spaceDataMapはA2から下に保存
};

// ============ メイン関数：バッチ処理を開始 ============
function updateSalesSheet() {
  const BATCH_SIZE = 30; // 30件ずつ処理
  
  try {
    const ss = SpreadsheetApp.openById(SPREADSHEET_ID);
    const sh = ss.getSheetByName(SHEET_NAME);
    
    deleteAllTriggersByName('processSimpleBatch');
    deleteAllTriggersByName('finalizeSimpleUpdate');
    
    let tempSheet = ss.getSheetByName(TEMP_SHEET_NAME);
    if (tempSheet) {
      tempSheet.clear();
    } else {
      tempSheet = ss.insertSheet(TEMP_SHEET_NAME);
      tempSheet.hideSheet();
    }
    
    const groups = [];
    const data = sh.getRange(2, 3, sh.getLastRow() - 1, 1).getDisplayValues();
    for (let i = 0; i < data.length; i += 3) {
      const id = data[i][0].toString().trim();
      if (!id) break;
      groups.push({ spaceId: id, row: i + 2 });
    }
    
    console.log(`処理対象: ${groups.length}件のスペース`);
    
    if (sh.getRange(1, 15).getValue() !== '2025年合計') {
      setupDateHeaders(sh);
    }
    
    const batches = [];
    for (let i = 0; i < groups.length; i += BATCH_SIZE) {
      batches.push(groups.slice(i, i + BATCH_SIZE));
    }
    
    tempSheet.getRange(TEMP_CELLS.BATCHES).setValue(JSON.stringify(batches));
    tempSheet.getRange(TEMP_CELLS.BATCH_INDEX).setValue('0');
    
    console.log(`${batches.length}個のバッチに分割しました`);
    
    ScriptApp.newTrigger('processSimpleBatch')
      .timeBased()
      .after(10 * 1000)
      .create();
    
    console.log('10秒後にバッチ処理を開始します。');

  } catch (error) {
    console.error('updateSalesSheet error:', error);
  }
}

// ============ バッチ処理関数（API呼び出し） ============
function processSimpleBatch() {
  const API_URL = 'https://a776jppz94.execute-api.ap-northeast-1.amazonaws.com/prod/getcompetitorsales';
  
  try {
    const ss = SpreadsheetApp.openById(SPREADSHEET_ID);
    const tempSheet = ss.getSheetByName(TEMP_SHEET_NAME);
    
    if (!tempSheet) {
      console.error('一時シートが見つかりません。処理を中断します。');
      deleteAllTriggersByName('processSimpleBatch');
      return;
    }
    
    const batches = JSON.parse(tempSheet.getRange(TEMP_CELLS.BATCHES).getValue());
    const batchIndex = parseInt(tempSheet.getRange(TEMP_CELLS.BATCH_INDEX).getValue());
    
    if (batchIndex >= batches.length) {
      console.log('全バッチ処理完了。最終処理を開始します。');
      tempSheet.getRange(TEMP_CELLS.FINALIZE_INDEX).setValue('0');
      
      deleteAllTriggersByName('processSimpleBatch');
      deleteAllTriggersByName('finalizeSimpleUpdate');
      ScriptApp.newTrigger('finalizeSimpleUpdate')
        .timeBased()
        .after(10 * 1000)
        .create();
      return;
    }
    
    let spaceDataMap = {};
    if (batchIndex > 0) {
      spaceDataMap = restoreDataFromSheet(tempSheet, TEMP_CELLS.SPACE_DATA_START);
    }
    
    const currentBatch = batches[batchIndex];
    console.log(`バッチ ${batchIndex + 1}/${batches.length} を処理中（${currentBatch.length}件）`);
    
    // ここではplanIdを指定しない。API側で全プランを取得させる
    const payload = { 
      queries: currentBatch.map(g => ({ spaceId: g.spaceId })) 
    };
    
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
    
    // APIからのレスポンスは `results` 配列に格納されている
    if (data.results && Array.isArray(data.results)) {
      data.results.forEach(result => {
        const spaceId = result.spaceId;
        if (!spaceDataMap[spaceId]) {
          spaceDataMap[spaceId] = { plans: [], defaultPlan: null, error: result.error || null };
        }
        
        if (!result.error && result.daily_sales) {
          // planDisplayName をAPIレスポンスから取得する
          let planName = result.planId || 'Unknown';
          if (result.daily_sales.length > 0) {
            for (const day of result.daily_sales) {
              if (day.reservations && day.reservations.length > 0) {
                planName = day.reservations[0].planDisplayName || planName;
                break;
              }
            }
          }
          
          const planInfo = {
            planId: result.planId,
            planName: planName,
            salesData: result.daily_sales
          };
          
          spaceDataMap[spaceId].plans.push(planInfo);
          if (!spaceDataMap[spaceId].defaultPlan) {
            spaceDataMap[spaceId].defaultPlan = planInfo;
          }
        }
      });
    }
    
    saveDataToSheet(tempSheet, TEMP_CELLS.SPACE_DATA_START, spaceDataMap);
    tempSheet.getRange(TEMP_CELLS.BATCH_INDEX).setValue(batchIndex + 1);
    
    deleteAllTriggersByName('processSimpleBatch');
    ScriptApp.newTrigger('processSimpleBatch')
      .timeBased()
      .after(30 * 1000)
      .create();
    
  } catch (error) {
    console.error('processSimpleBatch error:', error);
    deleteAllTriggersByName('processSimpleBatch');
    ScriptApp.newTrigger('processSimpleBatch')
      .timeBased()
      .after(60 * 1000)
      .create();
  }
}

// ============ 最終処理関数（スプレッドシート書き込み） ============
function finalizeSimpleUpdate() {
  const FINALIZE_BATCH_SIZE = 30;
  
  try {
    const ss = SpreadsheetApp.openById(SPREADSHEET_ID);
    const sh = ss.getSheetByName(SHEET_NAME);
    const tempSheet = ss.getSheetByName(TEMP_SHEET_NAME);
    
    if (!tempSheet) {
      console.error('一時シートが見つかりません。処理を中断します。');
      deleteAllTriggersByName('finalizeSimpleUpdate');
      return;
    }
    
    const batches = JSON.parse(tempSheet.getRange(TEMP_CELLS.BATCHES).getValue());
    const groups = batches.flat();
    const spaceDataMap = restoreDataFromSheet(tempSheet, TEMP_CELLS.SPACE_DATA_START);
    let planMappingCache = JSON.parse(tempSheet.getRange(TEMP_CELLS.PLAN_MAPPING).getValue() || '{}');
    const finalizeIndex = parseInt(tempSheet.getRange(TEMP_CELLS.FINALIZE_INDEX).getValue() || '0');
    
    console.log(`最終処理：${finalizeIndex + 1}〜${Math.min(finalizeIndex + FINALIZE_BATCH_SIZE, groups.length)}/${groups.length} 件を処理中`);
    
    const endIndex = Math.min(finalizeIndex + FINALIZE_BATCH_SIZE, groups.length);
    for (let i = finalizeIndex; i < endIndex; i++) {
      const { spaceId, row } = groups[i];
      const spaceData = spaceDataMap[spaceId];
      
      if (!spaceData || spaceData.error) {
        sh.getRange(row, 4).setValue('エラー');
        setTotalFormulas(sh, row);
        continue;
      }
      
      const planNames = [];
      const planMapping = {};
      spaceData.plans.forEach(plan => {
        planNames.push(plan.planName);
        planMapping[plan.planName] = plan.planId;
      });
      planMappingCache[spaceId] = planMapping;
      
      if (planNames.length > 0) {
        const rng = sh.getRange(row, 4, 3, 1);
        if (!rng.isPartOfMerge()) rng.merge();
        const rule = SpreadsheetApp.newDataValidation().requireValueInList(planNames, true).setAllowInvalid(false).build();
        rng.setDataValidation(rule);
        sh.getRange(row, 4).setValue(spaceData.defaultPlan.planName);
      }
      
      if (spaceData.defaultPlan) {
        updateSalesData(sh, row, spaceData.defaultPlan.salesData);
      }
      setTotalFormulas(sh, row);
    }
    
    tempSheet.getRange(TEMP_CELLS.PLAN_MAPPING).setValue(JSON.stringify(planMappingCache));
    tempSheet.getRange(TEMP_CELLS.FINALIZE_INDEX).setValue(endIndex.toString());
    
    deleteAllTriggersByName('finalizeSimpleUpdate');

    if (endIndex < groups.length) {
      ScriptApp.newTrigger('finalizeSimpleUpdate')
        .timeBased()
        .after(10 * 1000)
        .create();
    } else {
      console.log(`更新完了: ${groups.length}件のスペース`);
    }
    
  } catch (error) {
    console.error('finalizeSimpleUpdate error:', error);
    deleteAllTriggersByName('finalizeSimpleUpdate');
    ScriptApp.newTrigger('finalizeSimpleUpdate')
      .timeBased()
      .after(30 * 1000)
      .create();
  }
}

// ============ データ永続化ヘルパー関数 ============
function saveDataToSheet(sheet, startCell, data) {
  const mapStr = JSON.stringify(data);
  const blob = Utilities.newBlob(mapStr, 'text/plain', 'data.txt');
  blob.setDataFromString(mapStr, 'UTF-8');
  const encoded = Utilities.base64Encode(blob.getBytes());
  
  const CHUNK_SIZE = 50000;
  const startRow = sheet.getRange(startCell).getRow();
  const startCol = sheet.getRange(startCell).getColumn();

  const lastRow = sheet.getLastRow();
  if (lastRow >= startRow) {
    sheet.getRange(startRow, startCol, lastRow - startRow + 1, 1).clearContent();
  }
  
  const chunks = [];
  for (let i = 0; i < encoded.length; i += CHUNK_SIZE) {
    chunks.push([encoded.substring(i, i + CHUNK_SIZE)]);
  }
  if (chunks.length > 0) {
    sheet.getRange(startRow, startCol, chunks.length, 1).setValues(chunks);
  }
}

function restoreDataFromSheet(sheet, startCell) {
  const startRow = sheet.getRange(startCell).getRow();
  const startCol = sheet.getRange(startCell).getColumn();
  const lastRow = sheet.getLastRow();
  
  if (lastRow < startRow) return {};

  const range = sheet.getRange(startRow, startCol, lastRow - startRow + 1, 1);
  const encoded = range.getValues().map(row => row[0]).join('');
  
  if (!encoded) return {};
  
  try {
    const decoded = Utilities.base64Decode(encoded);
    const mapStr = Utilities.newBlob(decoded).getDataAsString('UTF-8');
    return JSON.parse(mapStr || '{}');
  } catch (e) {
    console.error('データ復元エラー:', e);
    return {};
  }
}

// ============ onEdit関数 ============
function onEdit(e) {
  if (!e) return;
  const sheet = e.range.getSheet();
  if (sheet.getName() !== SHEET_NAME) return;

  const col = e.range.getColumn();
  const row = e.range.getRow();
  
  if (col !== 4 || (row - 2) % 3 !== 0) return;

  const spaceId = sheet.getRange(row, 3).getDisplayValue().trim();
  const planName = e.range.getValue();
  
  if (!planName || planName === 'エラー' || !spaceId) return;
  
  fetchSelectedPlanData(sheet, row, spaceId, planName);
}

// ★★★★★ ここが今回のメインの修正箇所です ★★★★★
function fetchSelectedPlanData(sheet, row, spaceId, planName) {
  const API_URL = 'https://a776jppz94.execute-api.ap-northeast-1.amazonaws.com/prod/getcompetitorsales';
  
  try {
    sheet.getRange(row, 15).setValue('読込中...');
    SpreadsheetApp.flush();
    
    // 一時シートからplanIdを取得
    let planId = null;
    try {
      const ss = SpreadsheetApp.openById(SPREADSHEET_ID);
      const tempSheet = ss.getSheetByName(TEMP_SHEET_NAME);
      if (tempSheet) {
        const mappingStr = tempSheet.getRange(TEMP_CELLS.PLAN_MAPPING).getValue();
        if (mappingStr) {
          const mapping = JSON.parse(mappingStr);
          if (mapping[spaceId] && mapping[spaceId][planName]) {
            planId = mapping[spaceId][planName];
          }
        }
      }
    } catch (e) {
      console.error('プランマッピング取得エラー:', e);
    }

    if (!planId) {
      // マッピングが見つからない場合、APIを呼び出さずにエラーを表示して終了
      throw new Error(`プランIDが見つかりません。先に全体更新を実行してください。`);
    }

    // APIにplanIdを渡す
    const payload = {
      queries: [{ 
        spaceId: spaceId,
        planId: planId 
      }]
    };
    
    console.log(`API呼び出し (単一プラン): SpaceID=${spaceId}, PlanID=${planId}`);
    
    const res = UrlFetchApp.fetch(API_URL, {
      method: 'post',
      contentType: 'application/json',
      payload: JSON.stringify(payload),
      muteHttpExceptions: true
    });
    
    if (res.getResponseCode() !== 200) {
      throw new Error(`APIエラー: ${res.getResponseCode()} - ${res.getContentText()}`);
    }
    
    const data = JSON.parse(res.getContentText());
    
    // ★修正: APIのレスポンス形式(単一成功時)に合わせて修正
    if (data.daily_sales) {
      updateSalesData(sheet, row, data.daily_sales);
      console.log(`更新完了: SpaceID=${spaceId}, PlanName=${planName}`);
    } else {
      // エラー時や予期せぬ形式の場合
      const errorMessage = data.error || (data.results && data.results.length > 0 && data.results[0].error) || 'データなし';
      console.error(`プランデータ取得エラー: ${spaceId} - ${planName} - ${errorMessage}`);
      sheet.getRange(row, 15).setValue(errorMessage);
    }
    
    setTotalFormulas(sheet, row);
    
  } catch (error) {
    console.error('fetchSelectedPlanData error:', error.message);
    sheet.getRange(row, 15).setValue('エラー');
    // エラー時は数式を再設定して表示をリセット
    setTotalFormulas(sheet, row);
  }
}


// ============ ユーティリティ関数 ============
function deleteAllTriggersByName(functionName) {
  try {
    const triggers = ScriptApp.getProjectTriggers();
    triggers.forEach(trigger => {
      if (trigger.getHandlerFunction() === functionName) {
        ScriptApp.deleteTrigger(trigger);
      }
    });
  } catch(e) {
    console.error(`トリガーの削除中にエラーが発生しました: ${e.message}`);
  }
}

function deleteAllTriggers() {
  const triggers = ScriptApp.getProjectTriggers();
  triggers.forEach(trigger => {
    ScriptApp.deleteTrigger(trigger);
  });
  console.log(`${triggers.length}個のトリガーを削除しました`);
}

function stopAllProcesses() {
  deleteAllTriggersByName('processSimpleBatch');
  deleteAllTriggersByName('finalizeSimpleUpdate');
  console.log('すべてのバッチ処理・更新処理のトリガーを削除し、処理を停止しました。');
}

function cleanupTempSheet() {
  try {
    const ss = SpreadsheetApp.openById(SPREADSHEET_ID);
    const tempSheet = ss.getSheetByName(TEMP_SHEET_NAME);
    if (tempSheet) {
      ss.deleteSheet(tempSheet);
      console.log('一時シートを削除しました');
    }
  } catch (e) {
    console.error('一時シートの削除に失敗しました:', e);
  }
}

// ============ 元のコードに含まれる必須関数 ============
function setupDateHeaders(sheet) {
  const startCol = 15;
  let col = startCol;
  sheet.getRange(1, col).setValue('2025年合計');
  col++;
  
  for (let month = 6; month <= 12; month++) {
    sheet.getRange(1, col).setValue(`${month}月合計`);
    col++;
    const daysInMonth = new Date(2025, month, 0).getDate();
    const startDay = (month === 6) ? 11 : 1;
    for (let day = startDay; day <= daysInMonth; day++) {
      const dateStr = `2025/${String(month).padStart(2, '0')}/${String(day).padStart(2, '0')}`;
      sheet.getRange(1, col).setValue(dateStr);
      col++;
    }
  }
}

function updateSalesData(sheet, row, salesData) {
  const startCol = 15;
  const excludeMorning = sheet.getRange(row, 14).getValue() === true;
  const salesMap = {};
  let minDate = null;
  let maxDate = null;
  
  salesData.forEach(item => {
    let totalSales = item.total_sales || 0;
    if (excludeMorning && item.reservations && item.reservations.length > 0) {
      totalSales = 0;
      item.reservations.forEach(reservation => {
        if (!isInMorningRange(reservation.start_time)) {
          totalSales += reservation.price || 0;
        }
      });
    }
    salesMap[item.date] = totalSales;
    if (!minDate || item.date < minDate) minDate = item.date;
    if (!maxDate || item.date > maxDate) maxDate = item.date;
  });
  
  const lastCol = sheet.getLastColumn();
  const headers = sheet.getRange(1, startCol, 1, lastCol - startCol + 1).getValues()[0];
  const values = [];

  for (let i = 0; i < headers.length; i++) {
    let value = '';
    const header = headers[i];
    if (header instanceof Date || (typeof header === 'string' && header.match(/^\d{4}\/\d{2}\/\d{2}$/))) {
        const headerDate = new Date(header);
        const year = headerDate.getFullYear();
        const month = String(headerDate.getMonth() + 1).padStart(2, '0');
        const day = String(headerDate.getDate()).padStart(2, '0');
        const headerDateKey = `${year}-${month}-${day}`;

        if (salesMap.hasOwnProperty(headerDateKey)) {
            value = salesMap[headerDateKey];
        } else if (minDate && maxDate && headerDateKey >= minDate && headerDateKey <= maxDate) {
            value = 0;
        }
    }
    values.push(value);
  }
  
  sheet.getRange(row, startCol, 1, values.length).setValues([values]);
}

function isInMorningRange(timeStr) {
  if (!timeStr || typeof timeStr !== 'string') return false;
  const [hours, minutes] = timeStr.split(':').map(Number);
  return (hours * 60 + minutes) >= 360 && (hours * 60 + minutes) < 660;
}

function setTotalFormulas(sheet, row) {
  const startCol = 15;
  sheet.getRange(row, startCol).setFormula(createYearTotalFormula(row));
  let col = startCol + 1;
  for (let month = 6; month <= 12; month++) {
    sheet.getRange(row, col).setFormula(createMonthTotalFormula(row, month));
    const daysInMonth = new Date(2025, month, 0).getDate();
    const startDay = (month === 6) ? 11 : 1;
    col += (daysInMonth - startDay + 1) + 1;
  }
}

function createYearTotalFormula(row) {
  const ranges = [];
  let col = 17;
  for (let month = 6; month <= 12; month++) {
    const daysInMonth = new Date(2025, month, 0).getDate();
    const startDay = (month === 6) ? 11 : 1;
    const actualDays = daysInMonth - startDay + 1;
    ranges.push(`${columnToLetter(col)}${row}:${columnToLetter(col + actualDays - 1)}${row}`);
    col += actualDays + 1;
  }
  return `=SUM(${ranges.join(',')})`;
}

function createMonthTotalFormula(row, month) {
  let col = 17;
  for (let m = 6; m < month; m++) {
    const daysInMonth = new Date(2025, m, 0).getDate();
    const startDay = (m === 6) ? 11 : 1;
    col += (daysInMonth - startDay + 1) + 1;
  }
  const daysInMonth = new Date(2025, month, 0).getDate();
  const startDay = (month === 6) ? 11 : 1;
  const actualDays = daysInMonth - startDay + 1;
  return `=SUM(${columnToLetter(col)}${row}:${columnToLetter(col + actualDays - 1)}${row})`;
}

function columnToLetter(column) {
  let temp, letter = '';
  while (column > 0) {
    temp = (column - 1) % 26;
    letter = String.fromCharCode(temp + 65) + letter;
    column = (column - temp - 1) / 26;
  }
  return letter;
}
