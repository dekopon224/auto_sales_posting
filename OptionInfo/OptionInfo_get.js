function fetchSpaceOptionsAndUpdateSheet() {
  // スプレッドシートの取得
  const sheet = SpreadsheetApp.getActiveSheet();
  
  // APIのURL（実際のAPI Gateway URLに変更してください）
  const API_URL = 'https://a776jppz94.execute-api.ap-northeast-1.amazonaws.com/prod/getoptionInfo';
  
  try {
    // 1. C列からspaceIdを取得（2行目から空欄まで）
    const spaceIds = getSpaceIds(sheet);
    
    if (spaceIds.length === 0) {
      SpreadsheetApp.getUi().alert('spaceIdが見つかりませんでした。');
      return;
    }
    
    console.log(`取得したspaceIds: ${spaceIds.join(', ')}`);
    
    // 2. APIにリクエストを送信
    const responseData = fetchOptionsFromAPI(API_URL, spaceIds);
    
    if (!responseData || !responseData.spaces) {
      SpreadsheetApp.getUi().alert('APIからデータを取得できませんでした。');
      return;
    }
    
    // 3. スプレッドシートに書き込み
    writeDataToSheet(sheet, responseData.spaces, spaceIds);
    
  } catch (error) {
    console.error('エラーが発生しました:', error);
    SpreadsheetApp.getUi().alert(`エラーが発生しました: ${error.toString()}`);
  }
}

/**
 * C列からspaceIdを取得する
 * @param {Sheet} sheet - スプレッドシートのシート
 * @returns {Array} spaceIdの配列
 */
function getSpaceIds(sheet) {
  const spaceIds = [];
  let row = 2; // 2行目から開始
  
  while (true) {
    const cellValue = sheet.getRange(row, 3).getValue(); // C列 = 3
    
    // 空欄が見つかったら終了
    if (!cellValue || cellValue.toString().trim() === '') {
      break;
    }
    
    spaceIds.push(cellValue.toString());
    row++;
  }
  
  return spaceIds;
}

/**
 * APIにPOSTリクエストを送信してオプション情報を取得
 * @param {string} apiUrl - API Gateway URL
 * @param {Array} spaceIds - spaceIdの配列
 * @returns {Object} APIレスポンス
 */
function fetchOptionsFromAPI(apiUrl, spaceIds) {
  const payload = {
    spaceIds: spaceIds
  };
  
  const options = {
    method: 'post',
    contentType: 'application/json',
    payload: JSON.stringify(payload),
    muteHttpExceptions: true
  };
  
  try {
    const response = UrlFetchApp.fetch(apiUrl, options);
    const responseCode = response.getResponseCode();
    
    if (responseCode !== 200) {
      console.error(`APIエラー: ステータスコード ${responseCode}`);
      console.error(`レスポンス: ${response.getContentText()}`);
      return null;
    }
    
    return JSON.parse(response.getContentText());
    
  } catch (error) {
    console.error('API呼び出しエラー:', error);
    throw error;
  }
}

/**
 * スペース名とオプション情報をスプレッドシートに書き込む
 * @param {Sheet} sheet - スプレッドシートのシート
 * @param {Array} spaces - APIレスポンスのspaces配列
 * @param {Array} originalSpaceIds - 元のspaceId順序
 */
function writeDataToSheet(sheet, spaces, originalSpaceIds) {
  // spaceIdをキーとしたマップを作成（高速検索用）
  const spaceMap = {};
  spaces.forEach(space => {
    spaceMap[space.spaceId] = space;
  });
  
  // 各行に対してスペース名とオプション情報を書き込む
  originalSpaceIds.forEach((spaceId, index) => {
    const row = index + 2; // 2行目から開始
    const space = spaceMap[spaceId];
    
    if (!space || space.error) {
      // エラーまたはデータなしの場合
      sheet.getRange(row, 2).clearContent(); // B列をクリア
      clearOptionsInRow(sheet, row); // オプション列をクリア
      console.log(`spaceId ${spaceId}: データなしまたはエラー`);
      return;
    }
    
    // B列にスペース名を書き込む
    sheet.getRange(row, 2).setValue(space.name || '');
    
    // オプション情報を書き込む
    writeOptionsInRow(sheet, row, space.options || []);
  });
}

/**
 * 指定行のオプション列をクリア
 * @param {Sheet} sheet - スプレッドシートのシート
 * @param {number} row - 行番号
 */
function clearOptionsInRow(sheet, row) {
  // R列から始まるオプション列をクリア（最大50オプション分を想定）
  const startCol = 18; // R列 = 18
  const maxOptions = 50;
  const endCol = startCol + (maxOptions * 2) - 1;
  
  // 現在の値を取得
  const range = sheet.getRange(row, startCol, 1, endCol - startCol + 1);
  const values = range.getValues()[0];
  
  // 空でない最後のセルを見つける
  let lastNonEmptyCol = 0;
  for (let i = values.length - 1; i >= 0; i--) {
    if (values[i] && values[i].toString().trim() !== '') {
      lastNonEmptyCol = i + 1;
      break;
    }
  }
  
  if (lastNonEmptyCol > 0) {
    // 値をクリア（書式は保持）
    sheet.getRange(row, startCol, 1, lastNonEmptyCol).clearContent();
  }
}

/**
 * 指定行にオプション情報を書き込む
 * @param {Sheet} sheet - スプレッドシートのシート
 * @param {number} row - 行番号
 * @param {Array} options - オプション配列
 */
function writeOptionsInRow(sheet, row, options) {
  // まず既存のオプション列をクリア
  clearOptionsInRow(sheet, row);
  
  if (options.length === 0) {
    return;
  }
  
  // オプションデータを2次元配列に変換
  const optionValues = [];
  options.forEach((option, index) => {
    // R列、T列、V列... と2列ごとにオプション名
    // S列、U列、W列... と2列ごとに価格
    optionValues.push(option.name || '');
    optionValues.push(option.price || '');
  });
  
  // R列から書き込み開始
  const startCol = 18; // R列 = 18
  const range = sheet.getRange(row, startCol, 1, optionValues.length);
  
  // 2次元配列として設定
  range.setValues([optionValues]);
}