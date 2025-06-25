#!/bin/bash -ex

NAME=debbot

docker build -t ${NAME} .
docker rm -f ${NAME} || true
docker run --name ${NAME} -d --restart=unless-stopped ${NAME}
docker logs -f ${NAME}