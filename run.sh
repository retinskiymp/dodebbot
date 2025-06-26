#!/bin/bash -ex

mkdir -p ./db

NAME=slotbot

docker build -t ${NAME} .
docker rm -f ${NAME} || true

docker run -d --name ${NAME} \
    --restart=unless-stopped \
    -e BOT_TOKEN="" \
    -v $(pwd)/db:/app/db \
    ${NAME}

docker logs -f ${NAME}