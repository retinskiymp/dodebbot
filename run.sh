#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

DB_DIR="$HOME/.slotbot"
mkdir -p "$DB_DIR"

NAME="slotbot"
IMAGE_TAG="slotbot:1.0"

docker rm -f "$NAME" 2>/dev/null || true
docker rmi "$IMAGE_TAG" 2>/dev/null || true

docker build \
  --tag "$IMAGE_TAG" \
  "$SCRIPT_DIR"

docker run -d --name "$NAME" \
  --restart=unless-stopped \
  --env-file "$SCRIPT_DIR/.env" \
  -v "$DB_DIR:/app/db" \
  "$IMAGE_TAG"

docker logs -f "$NAME"
