# auto_sales_posting

# ビルド手順

docker build --no-cache --platform=linux/amd64 -t spaceinfo .

docker tag spaceinfo:latest 897729114300.dkr.ecr.ap-northeast-1.amazonaws.com/spaceinfo:latest

aws ecr get-login-password --region ap-northeast-1 --profile goburin | docker login --username AWS --password-stdin 897729114300.dkr.ecr.ap-northeast-1.amazonaws.com

docker push 897729114300.dkr.ecr.ap-northeast-1.amazonaws.com/spaceinfo:latest