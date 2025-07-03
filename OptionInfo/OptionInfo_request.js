/**
 * "施設情報"シートのA列2行目以降のURLをまとめて
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
  
  // 3. 20件ずつのバッチに分割して処理
  const batchSize = 20;
  const totalBatches = Math.ceil(urls.length / batchSize);
  
  for (let i = 0; i < totalBatches; i++) {
    const startIndex = i * batchSize;
    const endIndex = Math.min(startIndex + batchSize, urls.length);
    const batchUrls = urls.slice(startIndex, endIndex);
    
    // 3-1. ペイロード作成
    const payload = {
      urls: batchUrls
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
      Logger.log(`バッチ ${i + 1}/${totalBatches} (${batchUrls.length}件) を送信中...`);
      Logger.log(JSON.stringify(payload));
      const response = UrlFetchApp.fetch(apiUrl, options);
      Logger.log("HTTP ステータス: %s", response.getResponseCode());
      Logger.log("レスポンス: %s", response.getContentText());
    } catch (e) {
      Logger.log(`バッチ ${i + 1}/${totalBatches} のリクエスト失敗: %s`, e);
    }
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
  const values = range.getValues();
  const urls = values
    .map(row => row[0])
    .filter(url => url && url.toString().trim() !== "");

  if (urls.length === 0) {
    Logger.log("URLが見つかりませんでした");
    return;
  }

  // 3. URLを50件ずつに分割
  const chunkSize = 50; // 分割するURLの件数
  for (let i = 0; i < urls.length; i += chunkSize) {
    const chunk = urls.slice(i, i + chunkSize);

    // 4. ペイロード作成
    const payload = {
      urls: chunk
    };

    // 5. POST先エンドポイント
    const apiUrl = "https://a776jppz94.execute-api.ap-northeast-1.amazonaws.com/prod/spaceinfo";

    // 6. オプション設定
    const options = {
      method: "post",
      headers: {
        "Content-Type": "application/json; charset=UTF-8",
        "Accept":       "application/json"
      },
      payload: JSON.stringify(payload),
      muteHttpExceptions: true
    };

    // 7. リクエスト実行＆レスポンス確認
    try {
      Logger.log("送信ペイロード: %s", JSON.stringify(payload));
      const response = UrlFetchApp.fetch(apiUrl, options);
      Logger.log("HTTP ステータス: %s", response.getResponseCode());
      Logger.log("レスポンス: %s", response.getContentText());
      // 短時間での連続リクエストを避けるため、必要に応じて処理を一時停止 (例: Utilities.sleep(1000) で1秒待機)
      // Utilities.sleep(500); // 0.5秒待機
    } catch (e) {
      Logger.log("リクエスト失敗: %s", e);
    }
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
