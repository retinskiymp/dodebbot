#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

DB_DIR="$SCRIPT_DIR/../db_slot"
mkdir -p "$DB_DIR"

NAME=slotbot
IMAGE_TAG=slotbot:1.0

TARBALL="$DB_DIR/slotbot.tar"
if [[ -f "$TARBALL" ]] && ! docker image inspect "$IMAGE_TAG" &>/dev/null; then
  docker load -i "$TARBALL"
fi

docker rm -f "$NAME" 2>/dev/null || true

docker run -d --name "$NAME" \
  --restart=unless-stopped \
  --env-file "$SCRIPT_DIR/.env" \
  -v "$DB_DIR:/app/db" \
  "$IMAGE_TAG"

docker logs -f "$NAME"