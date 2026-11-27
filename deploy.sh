#!/usr/bin/env bash
set -e

DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

# Repair only the Git metadata and built web assets that root-owned commands
# may have left unreadable. Then use the rootless Docker context as dev.
if [ "$(id -u)" -eq 0 ]; then
  chown -R dev:dev "$DIR/.git" "$DIR/app/web"
  chmod -R u+rwX "$DIR/.git" "$DIR/app/web"
  chown dev:dev "$DIR/deploy.sh" "$DIR/Dockerfile.rootless"
  chmod 755 "$DIR/deploy.sh"
  exec sudo -u dev -H bash "$DIR/deploy.sh" "$@"
fi

cd "$DIR"

git pull --ff-only origin main

docker --context rootless build \
  --build-arg GISCLAW_BASE_IMAGE=shahrkav:runtime-base \
  -f Dockerfile.rootless -t shahrkav:isolated .

HOST_INDEX_BYTES="$(wc -c < app/web/index.html)"
IMAGE_INDEX_BYTES="$(docker --context rootless run --rm --entrypoint wc shahrkav:isolated -c /app/app/web/index.html | awk '{print $1}')"
if [ "$HOST_INDEX_BYTES" -eq 0 ] || [ "$HOST_INDEX_BYTES" != "$IMAGE_INDEX_BYTES" ]; then
  echo "deploy: app/web/index.html size mismatch (host=$HOST_INDEX_BYTES, image=$IMAGE_INDEX_BYTES); not restarting." >&2
  exit 1
fi

docker --context rootless compose -p shahrkav \
  -f docker-compose.rootless.yml -f docker-compose.server.yml \
  up -d --force-recreate --no-deps gisclaw

docker --context rootless compose -p shahrkav \
  -f docker-compose.rootless.yml -f docker-compose.server.yml ps

for attempt in {1..30}; do
  if docker --context rootless compose -p shahrkav \
    -f docker-compose.rootless.yml -f docker-compose.server.yml \
    exec -T gisclaw python -c \
    "import urllib.request; page=urllib.request.urlopen('http://127.0.0.1:8765/', timeout=3).read(); assert page, 'empty web page'; print('Shahrkav is up')" \
    2>/dev/null; then
    exit 0
  fi
  sleep 2
done

echo "deploy: application did not become ready within 60 seconds; recent logs:" >&2
docker --context rootless compose -p shahrkav \
  -f docker-compose.rootless.yml -f docker-compose.server.yml \
  logs --tail=80 gisclaw >&2
exit 1
