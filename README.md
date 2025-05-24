# auto_sales_posting

# 設定トリガー
postUrls_optioninfo　毎週月曜日午後11時〜0時
postUrls_spaceinfo　　毎日0時〜1時

fetchSpaceOptionsAndUpdateSheet　毎週火曜日0時〜1時
fetchSpaceInfoAndUpdateSheet　　毎日1時〜2時

# ビルド手順 spaceinfo

docker build --no-cache --platform=linux/amd64 -t spaceinfo .

docker tag spaceinfo:latest 897729114300.dkr.ecr.ap-northeast-1.amazonaws.com/spaceinfo:latest

aws ecr get-login-password --region ap-northeast-1 --profile goburin | docker login --username AWS --password-stdin 897729114300.dkr.ecr.ap-northeast-1.amazonaws.com

docker push 897729114300.dkr.ecr.ap-northeast-1.amazonaws.com/spaceinfo:latest

# ビルド手順 competitorsales

docker build --no-cache --platform=linux/amd64 -t competitorsales .

docker tag competitorsales:latest 897729114300.dkr.ecr.ap-northeast-1.amazonaws.com/competitorsales:latest

aws ecr get-login-password --region ap-northeast-1 --profile goburin | docker login --username AWS --password-stdin 897729114300.dkr.ecr.ap-northeast-1.amazonaws.com

docker push 897729114300.dkr.ecr.ap-northeast-1.amazonaws.com/competitorsales:latest

# ビルド手順 SpaceRate

docker build --no-cache --platform=linux/amd64 -t spacerate .

docker tag spacerate:latest 897729114300.dkr.ecr.ap-northeast-1.amazonaws.com/spacerate:latest

aws ecr get-login-password --region ap-northeast-1 --profile goburin | docker login --username AWS --password-stdin 897729114300.dkr.ecr.ap-northeast-1.amazonaws.com

docker push 897729114300.dkr.ecr.ap-northeast-1.amazonaws.com/spacerate:latest