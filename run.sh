#!/usr/bin/env bash
set -euo pipefail

mkdir -p ./db           # локальная папка под SQLite/файлы бота

NAME=slotbot            # как назвали сам образ/контейнер
IMAGE_TAG=slotbot:1.0

if [[ -f slotbot.tar ]] && ! docker image inspect "$IMAGE_TAG" &>/dev/null; then
  docker load -i slotbot.tar
fi

docker rm -f "$NAME" 2>/dev/null || true

docker run -d --name "$NAME" \
  --restart=unless-stopped \
  --env-file .env \
  -v "$(pwd)/db:/app/db" \
  "$IMAGE_TAG"

docker logs -f "$NAME"
