/**
 * “施設情報”シートのA列2行目以降のURLをまとめて
 * JSON { urls: […] } としてPOST送信するサンプル
 */
function postUrls_optioninfo() {
  // 1. スプレッドシート＆シート取得
  const ss    = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = ss.getSheetByName("施設情報");
  if (!sheet) {
    throw new Error("シート「施設情報」が見つかりません");
  }
  
  // 2. A列2行目から最終行までを取得し、空セルを除去
  const lastRow = sheet.getLastRow();
  if (lastRow < 2) {
    Logger.log("URLがありません");
    return;
  }
  const range = sheet.getRange(2, 1, lastRow - 1, 1);
  const values = range.getValues();            // [[url1], [url2], ...]
  const urls = values
    .map(row => row[0])
    .filter(url => url && url.toString().trim() !== "");

  if (urls.length === 0) {
    Logger.log("URLが見つかりませんでした");
    return;
  }
  
  // 3. ペイロード作成
  const payload = {
    urls: urls
  };

  // 4. POST先エンドポイント
  const apiUrl = "https://a776jppz94.execute-api.ap-northeast-1.amazonaws.com/prod/optionInfo";

  // 5. オプション設定
  const options = {
    method: "post",
    headers: {
    "Content-Type": "application/json; charset=UTF-8",
    "Accept":       "application/json"
  },
    payload: JSON.stringify(payload),
    muteHttpExceptions: true  // エラー時も内容を取得したい場合は true
  };

  // 6. リクエスト実行＆レスポンス確認
  try {
    Logger.log(JSON.stringify(payload));
    const response = UrlFetchApp.fetch(apiUrl, options);
    Logger.log("HTTP ステータス: %s", response.getResponseCode());
    Logger.log("レスポンス: %s", response.getContentText());
  } catch (e) {
    Logger.log("リクエスト失敗: %s", e);
  }
}

function postUrls_spaceinfo() {
  // 1. スプレッドシート＆シート取得
  const ss    = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = ss.getSheetByName("施設情報");
  if (!sheet) {
    throw new Error("シート「施設情報」が見つかりません");
  }
  
  // 2. A列2行目から最終行までを取得し、空セルを除去
  const lastRow = sheet.getLastRow();
  if (lastRow < 2) {
    Logger.log("URLがありません");
    return;
  }
  const range = sheet.getRange(2, 1, lastRow - 1, 1);
  const values = range.getValues();            // [[url1], [url2], ...]
  const urls = values
    .map(row => row[0])
    .filter(url => url && url.toString().trim() !== "");

  if (urls.length === 0) {
    Logger.log("URLが見つかりませんでした");
    return;
  }
  
  // 3. ペイロード作成
  const payload = {
    urls: urls
  };

  // 4. POST先エンドポイント
  const apiUrl = "https://a776jppz94.execute-api.ap-northeast-1.amazonaws.com/prod/spaceinfo";

  // 5. オプション設定
  const options = {
    method: "post",
    headers: {
    "Content-Type": "application/json; charset=UTF-8",
    "Accept":       "application/json"
  },
    payload: JSON.stringify(payload),
    muteHttpExceptions: true  // エラー時も内容を取得したい場合は true
  };

  // 6. リクエスト実行＆レスポンス確認
  try {
    Logger.log(JSON.stringify(payload));
    const response = UrlFetchApp.fetch(apiUrl, options);
    Logger.log("HTTP ステータス: %s", response.getResponseCode());
    Logger.log("レスポンス: %s", response.getContentText());
  } catch (e) {
    Logger.log("リクエスト失敗: %s", e);
  }
}

function postUrls_competitorsales() {
  // 1. スプレッドシート＆シート取得
  const ss    = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = ss.getSheetByName("施設情報");
  if (!sheet) {
    throw new Error("シート「施設情報」が見つかりません");
  }
  
  // 2. A列2行目から最終行までを取得し、空セルを除去
  const lastRow = sheet.getLastRow();
  if (lastRow < 2) {
    Logger.log("URLがありません");
    return;
  }
  const range = sheet.getRange(2, 1, lastRow - 1, 1);
  const values = range.getValues();            // [[url1], [url2], ...]
  const urls = values
    .map(row => row[0])
    .filter(url => url && url.toString().trim() !== "");

  if (urls.length === 0) {
    Logger.log("URLが見つかりませんでした");
    return;
  }
  
  // 3. ペイロード作成
  const payload = {
    urls: urls
  };

  // 4. POST先エンドポイント
  const apiUrl = "https://a776jppz94.execute-api.ap-northeast-1.amazonaws.com/prod/competitorsales";

  // 5. オプション設定
  const options = {
    method: "post",
    headers: {
    "Content-Type": "application/json; charset=UTF-8",
    "Accept":       "application/json"
  },
    payload: JSON.stringify(payload),
    muteHttpExceptions: true  // エラー時も内容を取得したい場合は true
  };

  // 6. リクエスト実行＆レスポンス確認
  try {
    Logger.log(JSON.stringify(payload));
    const response = UrlFetchApp.fetch(apiUrl, options);
    Logger.log("HTTP ステータス: %s", response.getResponseCode());
    Logger.log("レスポンス: %s", response.getContentText());
  } catch (e) {
    Logger.log("リクエスト失敗: %s", e);
  }
}

function postUrls_spacerate() {
  // 1. スプレッドシート＆シート取得
  const ss    = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = ss.getSheetByName("施設情報");
  if (!sheet) {
    throw new Error("シート「施設情報」が見つかりません");
  }
  
  // 2. A列2行目から最終行までを取得し、空セルを除去
  const lastRow = sheet.getLastRow();
  if (lastRow < 2) {
    Logger.log("URLがありません");
    return;
  }
  const range = sheet.getRange(2, 1, lastRow - 1, 1);
  const values = range.getValues();            // [[url1], [url2], ...]
  const urls = values
    .map(row => row[0])
    .filter(url => url && url.toString().trim() !== "");

  if (urls.length === 0) {
    Logger.log("URLが見つかりませんでした");
    return;
  }
  
  // 3. ペイロード作成
  const payload = {
    urls: urls
  };

  // 4. POST先エンドポイント
  const apiUrl = "https://a776jppz94.execute-api.ap-northeast-1.amazonaws.com/prod/spacerate";

  // 5. オプション設定
  const options = {
    method: "post",
    headers: {
      "Content-Type": "application/json; charset=UTF-8",
      "Accept":       "application/json"
    },
    payload: JSON.stringify(payload),
    muteHttpExceptions: true  // エラー時も内容を取得したい場合は true
  };

  // 6. リクエスト実行＆レスポンス確認
  try {
    Logger.log("スペースレートスクレイピング開始");
    Logger.log("対象URL数: %s", urls.length);
    Logger.log("ジョブ数: %s (URLs × 6期間)", urls.length * 6);
    Logger.log(JSON.stringify(payload));
    
    const response = UrlFetchApp.fetch(apiUrl, options);
    const responseCode = response.getResponseCode();
    const responseText = response.getContentText();
    
    Logger.log("HTTP ステータス: %s", responseCode);
    Logger.log("レスポンス: %s", responseText);
    
    // 成功時のレスポンスを解析
    if (responseCode === 200) {
      try {
        const result = JSON.parse(responseText);
        Logger.log("生成されたジョブ数: %s", result.total_jobs);
      } catch (e) {
        // JSON解析エラーは無視
      }
    }
  } catch (e) {
    Logger.log("リクエスト失敗: %s", e);
  }
}
