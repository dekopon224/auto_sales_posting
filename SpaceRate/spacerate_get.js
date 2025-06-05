/**
 * GAS から Lambda API をトリガーし、指定プランの「平均単価」を
 * シート "売上/単価" の G4 に出力する関数。
 * かつ、リクエスト JSON をログに出力するようにしています。
 */
function fetchAveragePriceAndWriteToSheet() {
  const SHEET_NAME = '単価/売上';
  const API_URL    = 'https://a776jppz94.execute-api.ap-northeast-1.amazonaws.com/prod/getspacerate'; // ← 実際のURLに置き換えてください

  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sh = ss.getSheetByName(SHEET_NAME);
  if (!sh) {
    SpreadsheetApp.getUi().alert(`シート「${SHEET_NAME}」が見つかりません`);
    return;
  }

  try {
    // ---（1）セルから値を読み取る部分---
    const spaceId       = sh.getRange('C2').getDisplayValue().toString().trim();
    const planDisplay   = sh.getRange('D2').getDisplayValue().toString().trim();
    const startDateText = sh.getRange('E2').getDisplayValue().toString().trim();
    const endDateText   = sh.getRange('G2').getDisplayValue().toString().trim();
    const startTimeText = sh.getRange('E3').getDisplayValue().toString().trim();
    const endTimeText   = sh.getRange('G3').getDisplayValue().toString().trim();
    const dayTypeJP     = sh.getRange('E4').getDisplayValue().toString().trim();

    if (!spaceId)       throw new Error('セル C2 に spaceId が設定されていません');
    if (!planDisplay)   throw new Error('セル D2 にプラン名が設定されていません');
    if (!startDateText || !endDateText) throw new Error('開始日または終了日が空欄です');
    if (!startTimeText || !endTimeText) throw new Error('開始時間または終了時間が空欄です');
    if (dayTypeJP !== '平日' && dayTypeJP !== '土日祝') throw new Error('セル E4 は「平日」または「土日祝」を選択してください');

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
    console.log('→ Lambda に送信するペイロード:', JSON.stringify(payload));

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

    // ---（9）G4 に書き込む---
    const outputCell = sh.getRange('G4');
    if (foundAverage !== null) {
      outputCell.setValue(foundAverage);
    } else {
      outputCell.setValue('該当プランが見つかりません');
    }

  } catch (err) {
    console.error(err);
    SpreadsheetApp.getUi().alert('エラー: ' + err.message);
  }
}
