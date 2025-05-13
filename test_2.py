import asyncio
from playwright.async_api import async_playwright

async def scrape_data(url):
    print(f"URLにアクセス中: {url}")
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/112.0.0.0 Safari/537.36'
        )
        page = await context.new_page()
        
        try:
            response = await page.goto(url, wait_until='networkidle', timeout=90000)
            
            if not response.ok:
                print(f"ページロードエラー: {response.status} {response.status_text}")
                return
                
            # デバッグ用：ページのHTMLを保存
            html_content = await page.content()
            with open('debug_page.html', 'w', encoding='utf-8') as f:
                f.write(html_content)
                print("デバッグ用にHTMLをdebug_page.htmlに保存しました")
            
            try:
                await page.wait_for_selector('.css-j3mvlq', timeout=10000)
            except Exception as e:
                print(f"要素 '.css-j3mvlq' が見つかりませんでした: {str(e)}")
                return
            
            # データを抽出し、記号をポイントに変換
            data = await page.evaluate('''() => {
                const buttons = document.querySelectorAll('.css-j3mvlq button');
                if (!buttons || buttons.length === 0) {
                    return [];
                }
                
                return Array.from(buttons).map(button => {
                    const day = button.querySelector('.css-7tvow, .css-qo22pl, .css-1fvi6cv')?.textContent || "";
                    const date = button.querySelector('.css-lw8eys, .css-b91hki, .css-19jz4op')?.textContent || "";
                    
                    // 記号をポイント(数値)に変換
                    let point = 0; // デフォルトは0
                    
                    if (button.querySelector('.icon-spm-double-circle')) {
                        point = 0; // 二重丸は0
                    } else if (button.querySelector('.icon-spm-single-circle')) {
                        point = 1; // 丸は1
                    } else if (button.querySelector('.icon-spm-triangle')) {
                        point = 2; // 三角は2
                    } // それ以外はデフォルトの0のまま
                    
                    return { day, date, point };
                });
            }''')
            
            if not data or len(data) == 0:
                print("指定した要素から日付と記号を取得できませんでした。")
                return
            
            # 結果を出力（ポイント形式）
            print("\n日付とポイントの一覧:")
            print("=" * 30)
            print("曜日\t日付\tポイント")
            print("-" * 30)
            for item in data:
                print(f"{item['day']}\t{item['date']}\t{item['point']}")
            print("=" * 30)
            
            # 元の記号も確認したい場合のための出力関数
            def get_symbol_name(point):
                if point == 0:
                    return "二重丸"
                elif point == 1:
                    return "丸"
                elif point == 2:
                    return "三角"
                else:
                    return "不明"
            
            print("\n参考：ポイントと記号の対応")
            print("0 = 二重丸, 1 = 丸, 2 = 三角")
            
        except Exception as e:
            print(f"スクレイピング中にエラーが発生しました: {str(e)}")
            import traceback
            print(traceback.format_exc())
        finally:
            try:
                await page.screenshot(path='error_screenshot.png', full_page=True)
                print("スクリーンショットを error_screenshot.png に保存しました")
            except Exception as screenshot_err:
                print(f"スクリーンショット撮影エラー: {str(screenshot_err)}")
                
            await browser.close()

async def main():
    print("=" * 50)
    print("日付とポイントスクレイパー")
    print("=" * 50)
    
    url = input("\nスクレイピングするURLを入力してください: ")
    
    await scrape_data(url)

if __name__ == "__main__":
    asyncio.run(main())