/**
 * スプレッドシートのメニューに「平均単価取得」を追加する
 */
function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('単価/売上ツール')
    .addItem('平均単価取得', 'fetchAveragePriceAndWriteToSheet')
    .addToUi();
}

/**
 * GAS から Lambda API をトリガーし、複数スペースの3つの異なる日時別単価を
 * シート "売上/単価" に出力する関数。
 * かつ、リクエスト JSON をログに出力するようにしています。
 */
function fetchAveragePriceAndWriteToSheet() {
  const SHEET_NAME = '単価/売上';
  const API_URL    = 'https://a776jppz94.execute-api.ap-northeast-1.amazonaws.com/prod/getspacerate'; // Lambda API の URL

  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sh = ss.getSheetByName(SHEET_NAME);
  if (!sh) {
    SpreadsheetApp.getUi().alert(`シート「${SHEET_NAME}」が見つかりません`);
    return;
  }

  // 可変のスペース数を処理（C2, C5, C8... の3行毎）
  let rowIndex = 2; // 開始行
  
  while (true) {
    // spaceId をチェック（空欄なら処理終了）
    const spaceId = sh.getRange(`C${rowIndex}`).getDisplayValue().toString().trim();
    if (!spaceId) {
      console.log(`行 ${rowIndex} でspaceIdが空欄のため処理を終了します`);
      break;
    }
    
    const planDisplay = sh.getRange(`D${rowIndex}`).getDisplayValue().toString().trim();
    console.log(`スペース処理開始: spaceId=${spaceId}, planDisplay=${planDisplay}, row=${rowIndex}`);
    
    // 各スペースで3つの条件を処理
    const conditions = [
      {
        name: '条件1',
        startDateCell: `E${rowIndex}`,
        endDateCell: `G${rowIndex}`,
        startTimeCell: `E${rowIndex + 1}`,
        endTimeCell: `G${rowIndex + 1}`,
        dayTypeCell: `E${rowIndex + 2}`,
        outputCell: `G${rowIndex + 2}`
      },
      {
        name: '条件2',
        startDateCell: `H${rowIndex}`,
        endDateCell: `J${rowIndex}`,
        startTimeCell: `H${rowIndex + 1}`,
        endTimeCell: `J${rowIndex + 1}`,
        dayTypeCell: `H${rowIndex + 2}`,
        outputCell: `J${rowIndex + 2}`
      },
      {
        name: '条件3',
        startDateCell: `K${rowIndex}`,
        endDateCell: `M${rowIndex}`,
        startTimeCell: `K${rowIndex + 1}`,
        endTimeCell: `M${rowIndex + 1}`,
        dayTypeCell: `K${rowIndex + 2}`,
        outputCell: `M${rowIndex + 2}`
      }
    ];
    
    // 各条件を処理
    conditions.forEach(condition => {
      try {
        processCondition(sh, spaceId, planDisplay, condition, API_URL);
      } catch (err) {
        console.error(`${condition.name} でエラーが発生しました: ${err.message}`);
        sh.getRange(condition.outputCell).setValue(`エラー: ${err.message}`);
      }
    });
    
    // 次のスペース行へ（3行毎）
    rowIndex += 3;
  }
  
  console.log('全スペースの処理が完了しました');
}

/**
 * 1つの条件を処理する関数
 */
function processCondition(sh, spaceId, planDisplay, condition, API_URL) {
  // ---（1）セルから値を読み取る部分---
  const startDateText = sh.getRange(condition.startDateCell).getDisplayValue().toString().trim();
  const endDateText   = sh.getRange(condition.endDateCell).getDisplayValue().toString().trim();
  const startTimeText = sh.getRange(condition.startTimeCell).getDisplayValue().toString().trim();
  const endTimeText   = sh.getRange(condition.endTimeCell).getDisplayValue().toString().trim();
  const dayTypeJP     = sh.getRange(condition.dayTypeCell).getDisplayValue().toString().trim();

  if (!planDisplay)   throw new Error('プラン名が設定されていません');
  if (!startDateText || !endDateText) throw new Error('開始日または終了日が空欄です');
  if (!startTimeText || !endTimeText) throw new Error('開始時間または終了時間が空欄です');
  if (dayTypeJP !== '平日' && dayTypeJP !== '土日祝') throw new Error('平日/土日祝は「平日」または「土日祝」を選択してください');

  // ---（2）日付フォーマット整形---
  const startDate = Utilities.formatDate(new Date(startDateText), Session.getScriptTimeZone(), 'yyyy-MM-dd');
  const endDate   = Utilities.formatDate(new Date(endDateText),   Session.getScriptTimeZone(), 'yyyy-MM-dd');

  // ---（3）時刻文字列から「時」を取り出して整数化---
  const parseHour = (timeStr) => {
    const m = timeStr.match(/^(\d{1,2})\s*:\s*\d{1,2}$/);
    if (!m) throw new Error(`時刻の書式が不正です: ${timeStr} (例: "0:00"、"9:00")`);
    return parseInt(m[1], 10);
  };
  const startHour = parseHour(startTimeText);
  const endHour   = parseHour(endTimeText);

  if (startDate > endDate) throw new Error('開始日が終了日より後になっています');
  if (startHour < 0 || startHour > 23 || endHour < 0 || endHour > 23) throw new Error('時刻は 0～23 の範囲で指定してください');
  if (startHour > endHour) throw new Error('開始時間が終了時間より後です');

  // ---（4）day_type の英語化---
  const dayType = (dayTypeJP === '平日') ? 'weekday' : 'weekend';

  // ---（5）Lambda に渡す JSON ペイロードを準備---
  const payload = {
    spaceId:    spaceId,
    start_date: startDate,
    end_date:   endDate,
    start_hour: startHour,
    end_hour:   endHour,
    day_type:   dayType
  };

  // ここでリクエスト JSON をログに出力しておく
  console.log(`→ Lambda に送信するペイロード (${condition.name}):`, JSON.stringify(payload));

  // ---（6）UrlFetchApp で POST リクエスト---
  const options = {
    method:             'post',
    contentType:       'application/json',
    payload:           JSON.stringify(payload),
    muteHttpExceptions: true
  };

  const response = UrlFetchApp.fetch(API_URL, options);
  const code = response.getResponseCode();
  if (code !== 200) {
    throw new Error(`Lambda API エラー: ステータスコード ${code}、レスポンス: ${response.getContentText()}`);
  }

  // ---（7）レスポンスを「二重に」パースせずに柔軟に扱う---
  let parsed;
  try {
    parsed = JSON.parse(response.getContentText());
  } catch (e) {
    throw new Error('レスポンスが JSON としてパースできません: ' + response.getContentText());
  }

  // 「statusCode / body」形式で返ってきた場合には parsed.body が文字列 JSON
  // 「body」キーがなければ parsed 自体が直接必要な中身とみなす
  let actual;
  if (parsed.body) {
    // parsed.body は JSON 文字列になっているはずなので、再度パース
    try {
      actual = JSON.parse(parsed.body);
    } catch (e) {
      throw new Error('parsed.body をパースできません: ' + parsed.body);
    }
  } else {
    // body フィールドがなければ、parsed 自体をそのまま中身とする
    actual = parsed;
  }

  // ---（8）actual の中身を使ってプランを探す---
  if (!actual.plans) {
    throw new Error('Lambda レスポンスに plans フィールドが見当たりません: ' + JSON.stringify(actual));
  }

  const plansObj = actual.plans;
  let foundAverage = null;
  for (const planId in plansObj) {
    const rec = plansObj[planId];
    if (rec.planDisplayName === planDisplay) {
      foundAverage = rec.average_price;
      break;
    }
  }

  // ---（9）指定されたセルに書き込む---
  const outputCell = sh.getRange(condition.outputCell);
  if (foundAverage !== null) {
    outputCell.setValue(foundAverage);
  } else {
    outputCell.setValue('該当プランが見つかりません');
  }
}
