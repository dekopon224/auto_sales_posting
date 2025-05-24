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
    
    // 2. APIにリクエストを送信（履歴も取得）
    const responseData = fetchOptionsFromAPI(API_URL, spaceIds);
    
    if (!responseData || !responseData.spaces) {
      SpreadsheetApp.getUi().alert('APIからデータを取得できませんでした。');
      return;
    }
    
    // 3. スプレッドシートに書き込み（履歴付き）
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
    spaceIds: spaceIds,
    historyLimit: 5  // 履歴を5件まで取得
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
    
    // オプション情報を書き込む（履歴付き）
    writeOptionsWithHistoryInRow(sheet, row, space.options || [], space.priceHistory || []);
  });
}

/**
 * 指定行のオプション列をクリア（履歴対応）
 * @param {Sheet} sheet - スプレッドシートのシート
 * @param {number} row - 行番号
 */
function clearOptionsInRow(sheet, row) {
  // R列から始まるオプション列をクリア（履歴を含めて大幅に拡張）
  const startCol = 18; // R列 = 18
  const maxCols = 200; // 履歴を含めて最大200列まで想定
  
  // 現在の値を取得
  const range = sheet.getRange(row, startCol, 1, maxCols);
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
 * 指定行にオプション情報と履歴を書き込む
 * @param {Sheet} sheet - スプレッドシートのシート
 * @param {number} row - 行番号
 * @param {Array} options - オプション配列
 * @param {Array} priceHistory - 価格履歴配列
 */
function writeOptionsWithHistoryInRow(sheet, row, options, priceHistory) {
  // まず既存のオプション列をクリア
  clearOptionsInRow(sheet, row);
  
  if (options.length === 0) {
    return;
  }
  
  // 履歴をオプション名ごとにグループ化
  const historyByOption = {};
  priceHistory.forEach(history => {
    const optionName = history.optionName;
    if (!historyByOption[optionName]) {
      historyByOption[optionName] = [];
    }
    historyByOption[optionName].push(history);
  });
  
  // 書き込み用データを準備
  const rowData = [];
  
  options.forEach((option, index) => {
    // オプション名と価格を追加
    rowData.push(option.name || '');
    rowData.push(option.price || '');
    
    // 該当するオプションの履歴があるかチェック
    const optionHistories = historyByOption[option.name] || [];
    
    if (optionHistories.length > 0) {
      // 「履歴」文字列を追加
      rowData.push('履歴');
      
      // 履歴内容を追加
      optionHistories.forEach(history => {
        const historyText = formatHistoryText(history);
        rowData.push(historyText);
      });
    }
  });
  
  if (rowData.length > 0) {
    // R列から書き込み開始
    const startCol = 18; // R列 = 18
    const range = sheet.getRange(row, startCol, 1, rowData.length);
    
    // 2次元配列として設定
    range.setValues([rowData]);
  }
}

/**
 * 履歴テキストをフォーマットする
 * @param {Object} history - 履歴オブジェクト
 * @returns {string} フォーマットされた履歴テキスト
 */
function formatHistoryText(history) {
  // 日時をフォーマット
  const timestamp = history.timestamp;
  let formattedDate = '';
  
  try {
    // ISO形式の日時を Date オブジェクトに変換
    const date = new Date(timestamp);
    if (!isNaN(date.getTime())) {
      // 日本時間での表示
      formattedDate = Utilities.formatDate(date, 'Asia/Tokyo', 'yyyy/MM/dd HH:mm');
    } else {
      formattedDate = timestamp; // 変換できない場合はそのまま
    }
  } catch (e) {
    formattedDate = timestamp; // エラーの場合はそのまま
  }
  
  // フォーマット: 「オプション名：変更前価格から変更後価格に変更（取得日時）」
  return `${history.optionName}：${history.oldPrice}から${history.newPrice}に変更（${formattedDate}）`;
}