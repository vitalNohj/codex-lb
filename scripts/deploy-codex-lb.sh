#!/usr/bin/env bash
# Deploy codex-lb from origin/main and restart the systemd user service.
#
# Env overrides:
#   CODEX_LB_DEPLOY_DIR          Install path (default: /home/nohj/personal/codex-lb)
#   CODEX_LB_SERVICE             systemd user unit (default: codex-lb.service)
#   CODEX_LB_DEPLOY_BRANCH       Branch to deploy (default: main)
#   CODEX_LB_DEPLOY_REMOTE       Git remote (default: origin)
#   CODEX_LB_DEPLOY_LOG_DIR      Log directory (default: ~/.local/state/codex-lb/deploy)
#   CODEX_LB_DEPLOY_ALLOW_DIRTY  Set to 1 to allow uncommitted changes (default: refuse)
#   CODEX_LB_HEALTH_URL          Post-restart probe (default: http://127.0.0.1:2455/health)
#   CODEX_LB_SKIP_FRONTEND       Set to 1 to skip bun install/build
#   CODEX_LB_SKIP_RESTART        Set to 1 to pull/build only (no systemd restart)
#
set -euo pipefail

DEPLOY_DIR="${CODEX_LB_DEPLOY_DIR:-/home/nohj/personal/codex-lb}"
SERVICE="${CODEX_LB_SERVICE:-codex-lb.service}"
BRANCH="${CODEX_LB_DEPLOY_BRANCH:-main}"
REMOTE="${CODEX_LB_DEPLOY_REMOTE:-origin}"
LOG_DIR="${CODEX_LB_DEPLOY_LOG_DIR:-${XDG_STATE_HOME:-$HOME/.local/state}/codex-lb/deploy}"
LOCK_FILE="${CODEX_LB_DEPLOY_LOCK:-$LOG_DIR/deploy.lock}"
ALLOW_DIRTY="${CODEX_LB_DEPLOY_ALLOW_DIRTY:-0}"
HEALTH_URL="${CODEX_LB_HEALTH_URL:-http://127.0.0.1:2455/health}"
SKIP_FRONTEND="${CODEX_LB_SKIP_FRONTEND:-0}"
SKIP_RESTART="${CODEX_LB_SKIP_RESTART:-0}"
HEALTH_RETRIES="${CODEX_LB_HEALTH_RETRIES:-30}"
HEALTH_SLEEP_SECS="${CODEX_LB_HEALTH_SLEEP_SECS:-2}"

UV_BIN="${UV_BIN:-$HOME/.local/bin/uv}"
BUN_BIN="${BUN_BIN:-$HOME/.bun/bin/bun}"
TS="$(date -u +%Y%m%dT%H%M%SZ)"
LOG_FILE="$LOG_DIR/deploy-$TS.log"
LATEST_LINK="$LOG_DIR/latest.log"

mkdir -p "$LOG_DIR"

# Duplicate stdout/stderr to the log file while keeping console/Actions output.
exec > >(tee -a "$LOG_FILE") 2>&1
ln -sfn "$LOG_FILE" "$LATEST_LINK"

log() {
  printf '[%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"
}

die() {
  log "ERROR: $*"
  exit 1
}

on_err() {
  local exit_code=$?
  local line=${1:-?}
  log "FAILED at line ${line} (exit ${exit_code})"
  log "--- deploy context ---"
  log "DEPLOY_DIR=$DEPLOY_DIR SERVICE=$SERVICE BRANCH=$BRANCH REMOTE=$REMOTE"
  log "LOG_FILE=$LOG_FILE"
  if [[ -d "$DEPLOY_DIR/.git" ]]; then
    log "git status:"
    git -C "$DEPLOY_DIR" status --short --branch || true
    log "git rev-parse HEAD:"
    git -C "$DEPLOY_DIR" rev-parse HEAD || true
  fi
  if command -v systemctl >/dev/null 2>&1; then
    log "systemctl --user status ${SERVICE}:"
    systemctl --user status "$SERVICE" --no-pager -l || true
    log "recent journal for ${SERVICE}:"
    journalctl --user -u "$SERVICE" -n 80 --no-pager || true
  fi
  log "Full log: $LOG_FILE"
  exit "$exit_code"
}
trap 'on_err $LINENO' ERR

require_cmd() {
  local cmd=$1
  local path=${2:-}
  if [[ -n "$path" && -x "$path" ]]; then
    return 0
  fi
  if command -v "$cmd" >/dev/null 2>&1; then
    return 0
  fi
  die "required command not found: $cmd${path:+ (expected at $path)}"
}

acquire_lock() {
  mkdir -p "$(dirname "$LOCK_FILE")"
  exec 9>"$LOCK_FILE"
  if ! flock -n 9; then
    die "another deploy holds $LOCK_FILE — aborting"
  fi
  log "acquired lock $LOCK_FILE"
}

refresh_launcher() {
  local src="$DEPLOY_DIR/scripts/deploy-codex-lb.sh"
  local dest="${CODEX_LB_DEPLOY_LAUNCHER:-$HOME/bin/deploy-codex-lb.sh}"
  if [[ -f "$src" ]]; then
    mkdir -p "$(dirname "$dest")"
    install -m 755 "$src" "$dest"
    log "refreshed launcher -> $dest"
  fi
}

wait_healthy() {
  local i
  for ((i = 1; i <= HEALTH_RETRIES; i++)); do
    if curl -fsS --max-time 3 "$HEALTH_URL" >/dev/null 2>&1; then
      log "health check OK ($HEALTH_URL) attempt $i/$HEALTH_RETRIES"
      return 0
    fi
    log "health check waiting ($i/$HEALTH_RETRIES) $HEALTH_URL"
    sleep "$HEALTH_SLEEP_SECS"
  done
  die "service did not become healthy at $HEALTH_URL after $HEALTH_RETRIES attempts"
}

log "=== codex-lb deploy start ==="
log "host=$(hostname) user=$(id -un) pid=$$"
log "DEPLOY_DIR=$DEPLOY_DIR"
log "SERVICE=$SERVICE BRANCH=$BRANCH REMOTE=$REMOTE"
log "LOG_FILE=$LOG_FILE"

acquire_lock

require_cmd git
require_cmd systemctl
require_cmd curl
require_cmd flock
[[ -x "$UV_BIN" ]] || require_cmd uv "$UV_BIN"
if [[ "$SKIP_FRONTEND" != "1" ]]; then
  [[ -x "$BUN_BIN" ]] || require_cmd bun "$BUN_BIN"
fi

[[ -d "$DEPLOY_DIR" ]] || die "deploy dir missing: $DEPLOY_DIR"
[[ -d "$DEPLOY_DIR/.git" ]] || die "not a git repo: $DEPLOY_DIR"
cd "$DEPLOY_DIR"

log "pre-deploy git state:"
git status --short --branch
BEFORE_SHA="$(git rev-parse HEAD)"
log "BEFORE_SHA=$BEFORE_SHA"

if [[ "$ALLOW_DIRTY" != "1" ]]; then
  if [[ -n "$(git status --porcelain)" ]]; then
    die "working tree dirty under $DEPLOY_DIR — commit/stash/move WIP, or set CODEX_LB_DEPLOY_ALLOW_DIRTY=1"
  fi
fi

log "fetching $REMOTE $BRANCH"
git fetch --prune "$REMOTE" "$BRANCH"

REMOTE_SHA="$(git rev-parse "$REMOTE/$BRANCH")"
log "REMOTE_SHA=$REMOTE_SHA"

if [[ "$BEFORE_SHA" == "$REMOTE_SHA" ]] && [[ "$(git rev-parse --abbrev-ref HEAD)" == "$BRANCH" ]]; then
  log "already at $REMOTE_SHA on $BRANCH — still rebuilding/restarting to keep deploy idempotent"
else
  log "checking out $BRANCH"
  git checkout "$BRANCH"
  log "fast-forward pull $REMOTE/$BRANCH"
  git pull --ff-only "$REMOTE" "$BRANCH"
fi

AFTER_SHA="$(git rev-parse HEAD)"
log "AFTER_SHA=$AFTER_SHA"
git log -1 --oneline

log "syncing Python deps (uv sync)"
"$UV_BIN" sync

if [[ "$SKIP_FRONTEND" != "1" ]]; then
  log "installing frontend deps (bun install --frozen-lockfile)"
  (
    cd frontend
    "$BUN_BIN" install --frozen-lockfile
    log "building frontend (bun run build) -> app/static"
    "$BUN_BIN" run build
  )
  [[ -f app/static/index.html ]] || die "frontend build missing app/static/index.html"
else
  log "skipping frontend (CODEX_LB_SKIP_FRONTEND=1)"
fi

refresh_launcher

if [[ "$SKIP_RESTART" == "1" ]]; then
  log "skipping restart (CODEX_LB_SKIP_RESTART=1)"
else
  log "restarting systemd user unit: $SERVICE"
  systemctl --user restart "$SERVICE"
  systemctl --user reset-failed "$SERVICE" >/dev/null 2>&1 || true
  if ! systemctl --user is-active --quiet "$SERVICE"; then
    die "$SERVICE is not active after restart"
  fi
  log "$SERVICE is active"
  wait_healthy
fi

log "=== codex-lb deploy success ==="
log "deployed $BEFORE_SHA -> $AFTER_SHA"
log "log: $LOG_FILE"
exit 0
