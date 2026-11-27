#!/usr/bin/env bash
set -e

DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

# The rootless Docker context belongs to dev, not root.
if [ "$(id -u)" -eq 0 ]; then
  exec sudo -u dev -H bash "$DIR/deploy.sh" "$@"
fi

cd "$DIR"

git pull --ff-only origin main

docker --context rootless build \
  --build-arg GISCLAW_BASE_IMAGE=shahrkav:runtime-base \
  -f Dockerfile.rootless -t shahrkav:isolated .

docker --context rootless compose -p shahrkav \
  -f docker-compose.rootless.yml -f docker-compose.server.yml \
  up -d --force-recreate --no-deps gisclaw

docker --context rootless compose -p shahrkav \
  -f docker-compose.rootless.yml -f docker-compose.server.yml ps
