function fetchSpaceInfoAndUpdateSheet() {
  // スプレッドシートIDをここで指定します
  const SPREADSHEET_ID = "1YLt2IWtMPjkD9oi7XaF3scInkiffshv1SYnEjlbqoCo";
  const ss = SpreadsheetApp.openById(SPREADSHEET_ID);
  
  // 実行環境を判定
  const isTimeTrigger = !ss.getActiveSheet();
  
  // シート名を明示的に指定
  const sheet = ss.getSheetByName('施設情報');
  
  // シートが存在しない場合のエラーハンドリング
  if (!sheet) {
    console.error('「施設情報」シートが見つかりません');
    if (!isTimeTrigger) {
      SpreadsheetApp.getUi().alert('「施設情報」シートが見つかりません');
    }
    return;
  }
  
  // APIのURL
  const API_URL = 'https://a776jppz94.execute-api.ap-northeast-1.amazonaws.com/prod/getspaceinfo';
  
  try {
    // 1. C列からroom_idを取得（2行目から空欄まで）
    const roomIds = getRoomIds(sheet);
    
    if (roomIds.length === 0) {
      console.error('room_idが見つかりませんでした。');
      if (!isTimeTrigger) {
        SpreadsheetApp.getUi().alert('room_idが見つかりませんでした。');
      }
      return;
    }
    
    console.log(`取得したroom_ids: ${roomIds.join(', ')}`);
    
    // 2. APIにリクエストを送信
    const responseData = fetchRoomInfoFromAPI(API_URL, roomIds);
    
    if (!responseData || !responseData.rooms) {
      console.error('APIからデータを取得できませんでした。');
      if (!isTimeTrigger) {
        SpreadsheetApp.getUi().alert('APIからデータを取得できませんでした。');
      }
      return;
    }
    
    // 3. スプレッドシートに書き込み
    writeRoomDataToSheet(sheet, responseData.rooms, roomIds);
    
    // 成功ログ
    console.log('データの更新が完了しました。');
    
  } catch (error) {
    console.error('エラーが発生しました:', error);
    if (!isTimeTrigger) {
      SpreadsheetApp.getUi().alert(`エラーが発生しました: ${error.toString()}`);
    }
  }
}

/**
 * C列からroom_idを取得する
 * @param {GoogleAppsScript.Spreadsheet.Sheet} sheet - スプレッドシートのシート
 * @returns {Array<string>} room_idの配列
 */
function getRoomIds(sheet) {
  const roomIds = [];
  let row = 2; // 2行目から開始
  
  while (true) {
    const cellValue = sheet.getRange(row, 3).getValue(); // C列 = 3
    
    // 空欄が見つかったら終了
    if (!cellValue || cellValue.toString().trim() === '') {
      break;
    }
    
    roomIds.push(cellValue.toString());
    row++;
  }
  
  return roomIds;
}

/**
 * APIにPOSTリクエストを送信してスペース情報を取得
 * @param {string} apiUrl - API Gateway URL
 * @param {Array<string>} roomIds - room_idの配列
 * @returns {Object | null} APIレスポンス
 */
function fetchRoomInfoFromAPI(apiUrl, roomIds) {
  const payload = {
    room_ids: roomIds
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
 * スペース情報をスプレッドシートに書き込む
 * @param {GoogleAppsScript.Spreadsheet.Sheet} sheet - スプレッドシートのシート
 * @param {Array<Object>} rooms - APIレスポンスのrooms配列
 * @param {Array<string>} originalRoomIds - 元のroom_id順序
 */
function writeRoomDataToSheet(sheet, rooms, originalRoomIds) {
  // room_idをキーとしたマップを作成（高速検索用）
  const roomMap = {};
  rooms.forEach(room => {
    roomMap[room.room_id] = room;
  });
  
  // 日付ヘッダーを設定（K列〜Q列）
  const firstRoom = rooms.find(room => room.found && room.daily_points && room.daily_points.length > 0);
  if (firstRoom && firstRoom.daily_points) {
    writeDateHeaders(sheet, firstRoom.daily_points);
  }
  
  // 各行に対してスペース情報を書き込む
  originalRoomIds.forEach((roomId, index) => {
    const row = index + 2; // 2行目から開始
    const room = roomMap[roomId];
    
    if (!room || !room.found) {
      // エラーまたはデータなしの場合、該当列をクリア
      clearRoomInfoInRow(sheet, row);
      console.log(`room_id ${roomId}: データなしまたはエラー`);
      return;
    }
    
    // B列に施設名を書き込む
    sheet.getRange(row, 2).setValue(room.name || '');         // B列: name（施設名）
    
    // D列〜I列に基本情報を書き込む
    sheet.getRange(row, 4).setValue(room.location || '');     // D列: location
    sheet.getRange(row, 5).setValue(room.station || '');      // E列: station
    sheet.getRange(row, 6).setValue(room.capacity || '');     // F列: capacity
    sheet.getRange(row, 7).setValue(room.stay_capacity || ''); // G列: stay_capacity
    sheet.getRange(row, 8).setValue(room.floor_space || '');  // H列: floor_space
    sheet.getRange(row, 9).setValue(room.space_type || '');   // I列: space_type
    
    // K列〜Q列に日付ごとのポイントを書き込む
    writePointsInRow(sheet, row, room.daily_points || []);
  });
}

/**
 * 日付ヘッダーをK列〜Q列の1行目に書き込む
 * @param {GoogleAppsScript.Spreadsheet.Sheet} sheet - スプレッドシートのシート
 * @param {Array<Object>} dailyPoints - 日付ポイント配列
 */
function writeDateHeaders(sheet, dailyPoints) {
  const headerRow = 1;
  const startCol = 11; // K列 = 11
  
  // 最大7日分の日付を書き込む
  dailyPoints.slice(0, 7).forEach((pointData, index) => {
    const col = startCol + index;
    // 日付のみを抽出（YYYY-MM-DD → MM/DD形式）
    const dateStr = pointData.date;
    const formattedDate = formatDateHeader(dateStr);
    sheet.getRange(headerRow, col).setValue(formattedDate);
  });
}

/**
 * 日付を表示用にフォーマット
 * @param {string} dateStr - YYYY-MM-DD形式の日付文字列
 * @returns {string} MM/DD形式の日付文字列
 */
function formatDateHeader(dateStr) {
  try {
    const dateParts = dateStr.split('-');
    if (dateParts.length === 3) {
      const month = parseInt(dateParts[1], 10);
      const day = parseInt(dateParts[2], 10);
      return `${month}/${day}`;
    }
  } catch (e) {
    // エラーの場合はそのまま返す
  }
  return dateStr;
}

/**
 * 指定行のスペース情報列をクリア
 * @param {GoogleAppsScript.Spreadsheet.Sheet} sheet - スプレッドシートのシート
 * @param {number} row - 行番号
 */
function clearRoomInfoInRow(sheet, row) {
  // B列をクリア（施設名）
  sheet.getRange(row, 2).clearContent();
  
  // D列〜I列をクリア（基本情報）
  sheet.getRange(row, 4, 1, 6).clearContent();
  
  // K列〜Q列をクリア（ポイント情報）
  sheet.getRange(row, 11, 1, 7).clearContent();
}

/**
 * 指定行にポイント情報を書き込む（K列〜Q列）
 * @param {GoogleAppsScript.Spreadsheet.Sheet} sheet - スプレッドシートのシート
 * @param {number} row - 行番号
 * @param {Array<Object>} dailyPoints - 日付ポイント配列
 */
function writePointsInRow(sheet, row, dailyPoints) {
  const startCol = 11; // K列 = 11
  
  // 最大7日分のポイントを書き込む
  dailyPoints.slice(0, 7).forEach((pointData, index) => {
    const col = startCol + index;
    const point = pointData.point;
    
    // ポイント値を書き込み（小数点がある場合は表示、ない場合は整数表示）
    const displayValue = point % 1 === 0 ? point.toString() : point.toString();
    sheet.getRange(row, col).setValue(displayValue);
  });
}
