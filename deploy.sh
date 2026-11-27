#!/usr/bin/env bash
set -Eeuo pipefail

# Safe, isolated deployment for the Shahrkav rootless Compose project.
# Run as the Linux account that owns the rootless Docker context (e.g. dev),
# from any directory. This script never touches the system Docker daemon or
# other Compose projects.

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
BRANCH="${DEPLOY_BRANCH:-main}"
APP_IMAGE="${GISCLAW_APP_IMAGE:-shahrkav:isolated}"
BASE_IMAGE="${GISCLAW_BASE_IMAGE:-shahrkav:runtime-base}"
COMPOSE_ARGS=(--context rootless compose --project-directory "$PROJECT_DIR" -p shahrkav
  -f "$PROJECT_DIR/docker-compose.rootless.yml"
  -f "$PROJECT_DIR/docker-compose.server.yml")

die() { printf 'deploy: %s\n' "$*" >&2; exit 1; }
info() { printf '\n==> %s\n' "$*"; }

[[ "$(id -u)" -ne 0 ]] || die "با کاربر مالک Docker روت‌لس اجرا کن (مثلاً: sudo -u dev -H ./deploy.sh)، نه root."
command -v git >/dev/null || die 'git نصب نیست.'
command -v docker >/dev/null || die 'docker نصب نیست.'

cd "$PROJECT_DIR"
git rev-parse --is-inside-work-tree >/dev/null 2>&1 || die 'پوشهٔ اسکریپت، مخزن Git نیست.'
CURRENT_BRANCH="$(git branch --show-current)"
[[ -n "$CURRENT_BRANCH" ]] || die 'مخزن در حالت detached HEAD است؛ ابتدا روی شاخهٔ deploy قرار بگیر.'
[[ "$CURRENT_BRANCH" == "$BRANCH" ]] || die "شاخهٔ فعلی '$CURRENT_BRANCH' است، ولی شاخهٔ deploy '$BRANCH' تعیین شده."

if [[ -n "$(git status --porcelain --untracked-files=normal)" ]]; then
  git status --short >&2
  die 'تغییر محلی یا فایلِ ثبت‌نشده وجود دارد؛ برای جلوگیری از تداخل، ابتدا آن را بررسی/ثبت یا منتقل کن.'
fi

info "بررسی Docker context و image پایه"
docker --context rootless context inspect rootless >/dev/null 2>&1 || die "Docker context 'rootless' برای این کاربر موجود نیست."
docker --context rootless image inspect "$BASE_IMAGE" >/dev/null 2>&1 || die "image پایهٔ '$BASE_IMAGE' در daemon روت‌لس نیست؛ آن را یک‌بار آماده کن."

info "دریافت تغییرات شاخهٔ $BRANCH"
git pull --ff-only origin "$BRANCH"

[[ -s "$PROJECT_DIR/app/web/index.html" ]] || die 'فایل‌های آمادهٔ فرانت‌اند در app/web پیدا نشدند.'

info "ساخت image ایزولهٔ $APP_IMAGE"
docker --context rootless build \
  --build-arg "GISCLAW_BASE_IMAGE=$BASE_IMAGE" \
  -f "$PROJECT_DIR/Dockerfile.rootless" \
  -t "$APP_IMAGE" "$PROJECT_DIR"

info 'بررسی دسترسی worker به کد و وابستگی‌های GIS'
docker --context rootless run --rm --network none --user 65534:65534 \
  --entrypoint python "$APP_IMAGE" -c \
  "from pathlib import Path; Path('/app/app/isolated_worker.py').read_text(); from src.agent.react_agent import GISReActAgent; from src.agent import geo_ops; print('worker imports ok')"

info 'اعتبارسنجی Compose'
"${COMPOSE_ARGS[@]}" config --quiet

info 'بازسازی فقط سرویس شهرکاو'
"${COMPOSE_ARGS[@]}" up -d --force-recreate --no-deps gisclaw

info 'بررسی آماده‌شدن برنامه'
ready=0
for attempt in {1..30}; do
  if "${COMPOSE_ARGS[@]}" exec -T gisclaw python -c \
    "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/', timeout=3)" \
    >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 2
done

"${COMPOSE_ARGS[@]}" ps
[[ "$ready" -eq 1 ]] || die 'برنامه در مهلت مقرر آماده نشد؛ با docker compose logs سرویس gisclaw را بررسی کن.'
printf '\nاستقرار شهرکاو با موفقیت انجام شد.\n'
