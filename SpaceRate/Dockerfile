# 関数のディレクトリを定義
ARG FUNCTION_DIR="/function"

# Python13.13のベースイメージを使用
FROM python:3.13

# このビルドステージでグローバル引数を含める
ARG FUNCTION_DIR

ENV PLAYWRIGHT_BROWSERS_PATH=/playwright

# 関数のコードをコピーする
RUN mkdir -p ${FUNCTION_DIR}
COPY requirements.txt ${FUNCTION_DIR}

# 作業ディレクトリを関数のルートディレクトリに設定する
WORKDIR ${FUNCTION_DIR}

# 関数の依存関係をインストール
RUN pip install -r requirements.txt && \
    playwright install --with-deps chromium

COPY app.py ${FUNCTION_DIR}

# コンテナランタイムのデフォルトコマンドとしてランタイムインターフェースクライアントを設定
ENTRYPOINT [ "/usr/local/bin/python", "-m", "awslambdaric" ]
# 関数の名前を渡す
CMD [ "app.lambda_handler" ]