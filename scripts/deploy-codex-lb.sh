#!/usr/bin/env bash
# Deploy codex-lb from origin/main and restart the systemd user service.
#
# Env overrides:
#   CODEX_LB_DEPLOY_DIR            Install path (default: /home/nohj/personal/codex-lb)
#   CODEX_LB_SERVICE               systemd user unit (default: codex-lb.service)
#   CODEX_LB_DEPLOY_BRANCH         Branch to deploy (default: main)
#   CODEX_LB_DEPLOY_REMOTE         Git remote (default: origin)
#   CODEX_LB_DEPLOY_LOG_DIR        Log directory (default: ~/.local/state/codex-lb/deploy)
#   CODEX_LB_DEPLOY_ALLOW_DIRTY    Set to 1 to allow uncommitted changes (default: refuse)
#   CODEX_LB_DEPLOY_SWITCH_BRANCH  Set to 1 to checkout BRANCH when the clone is elsewhere
#   CODEX_LB_HEALTH_URL            Post-restart probe (default: http://127.0.0.1:2455/health/live)
#   CODEX_LB_SKIP_FRONTEND         Set to 1 to skip bun install/build
#   CODEX_LB_SKIP_RESTART          Set to 1 to pull/build only (no systemd restart)
#   CODEX_LB_DEPLOY_LAUNCHER       Path to refresh after a successful pull
#
set -euo pipefail

DEPLOY_DIR="${CODEX_LB_DEPLOY_DIR:-/home/nohj/personal/codex-lb}"
SERVICE="${CODEX_LB_SERVICE:-codex-lb.service}"
BRANCH="${CODEX_LB_DEPLOY_BRANCH:-main}"
REMOTE="${CODEX_LB_DEPLOY_REMOTE:-origin}"
LOG_DIR="${CODEX_LB_DEPLOY_LOG_DIR:-${XDG_STATE_HOME:-$HOME/.local/state}/codex-lb/deploy}"
LOCK_FILE="${CODEX_LB_DEPLOY_LOCK:-$LOG_DIR/deploy.lock}"
ALLOW_DIRTY="${CODEX_LB_DEPLOY_ALLOW_DIRTY:-0}"
SWITCH_BRANCH="${CODEX_LB_DEPLOY_SWITCH_BRANCH:-0}"
HEALTH_URL="${CODEX_LB_HEALTH_URL:-http://127.0.0.1:2455/health/live}"
SKIP_FRONTEND="${CODEX_LB_SKIP_FRONTEND:-0}"
SKIP_RESTART="${CODEX_LB_SKIP_RESTART:-0}"
HEALTH_RETRIES="${CODEX_LB_HEALTH_RETRIES:-45}"
HEALTH_SLEEP_SECS="${CODEX_LB_HEALTH_SLEEP_SECS:-2}"
ACTIVE_RETRIES="${CODEX_LB_ACTIVE_RETRIES:-30}"
LOG_KEEP="${CODEX_LB_DEPLOY_LOG_KEEP:-20}"

UV_BIN="${UV_BIN:-$HOME/.local/bin/uv}"
BUN_BIN="${BUN_BIN:-$HOME/.bun/bin/bun}"
TS="$(date -u +%Y%m%dT%H%M%SZ)"
LOG_FILE="$LOG_DIR/deploy-$TS.log"
LATEST_LINK="$LOG_DIR/latest.log"
DUMPED=0

mkdir -p "$LOG_DIR"

if command -v stdbuf >/dev/null 2>&1; then
  exec > >(stdbuf -oL tee -a "$LOG_FILE") 2>&1
else
  exec > >(tee -a "$LOG_FILE") 2>&1
fi
ln -sfn "$LOG_FILE" "$LATEST_LINK"

export GIT_TERMINAL_PROMPT=0

log() {
  printf '[%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"
}

dump_diagnostics() {
  if [[ "$DUMPED" == "1" ]]; then
    return 0
  fi
  DUMPED=1
  trap - ERR
  set +e
  log "--- deploy context ---"
  log "DEPLOY_DIR=$DEPLOY_DIR SERVICE=$SERVICE BRANCH=$BRANCH REMOTE=$REMOTE"
  log "SWITCH_BRANCH=$SWITCH_BRANCH SKIP_FRONTEND=$SKIP_FRONTEND SKIP_RESTART=$SKIP_RESTART"
  log "HEALTH_URL=$HEALTH_URL"
  log "LOG_FILE=$LOG_FILE"
  log "user=$(id -un) uid=$(id -u) HOME=$HOME"
  log "XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR:-unset}"
  log "DBUS_SESSION_BUS_ADDRESS=${DBUS_SESSION_BUS_ADDRESS:-unset}"
  if [[ -d "$DEPLOY_DIR/.git" ]]; then
    log "git status:"
    git -C "$DEPLOY_DIR" status --short --branch
    log "HEAD=$(git -C "$DEPLOY_DIR" rev-parse HEAD 2>/dev/null)"
  fi
  if command -v systemctl >/dev/null 2>&1; then
    log "systemctl --user is-active ${SERVICE}: $(systemctl --user is-active "$SERVICE" 2>/dev/null)"
    log "systemctl --user status ${SERVICE}:"
    systemctl --user status "$SERVICE" --no-pager -l
    log "recent journal for ${SERVICE}:"
    journalctl --user -u "$SERVICE" -n 80 --no-pager
  fi
  log "Full log: $LOG_FILE"
  set -e
}

die() {
  log "ERROR: $*"
  dump_diagnostics
  exit 1
}

on_err() {
  local exit_code=$?
  local line=${1:-?}
  log "FAILED at line ${line} (exit ${exit_code})"
  dump_diagnostics
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

require_int() {
  local name=$1
  local value=$2
  if [[ ! "$value" =~ ^[1-9][0-9]*$ ]]; then
    die "$name must be a positive integer (got ${value@Q})"
  fi
}

ensure_user_systemd() {
  local uid
  uid="$(id -u)"
  if [[ -z "${XDG_RUNTIME_DIR:-}" ]]; then
    export XDG_RUNTIME_DIR="/run/user/${uid}"
    log "set XDG_RUNTIME_DIR=$XDG_RUNTIME_DIR"
  fi
  if [[ -z "${DBUS_SESSION_BUS_ADDRESS:-}" ]]; then
    export DBUS_SESSION_BUS_ADDRESS="unix:path=${XDG_RUNTIME_DIR}/bus"
    log "set DBUS_SESSION_BUS_ADDRESS=$DBUS_SESSION_BUS_ADDRESS"
  fi
  if [[ ! -S "${XDG_RUNTIME_DIR}/bus" ]]; then
    die "user systemd bus missing at ${XDG_RUNTIME_DIR}/bus — run the runner as the linger user (nohj), not a system service"
  fi
  if ! systemctl --user show-environment >/dev/null 2>&1; then
    die "systemctl --user is not available in this session"
  fi
}

acquire_lock() {
  mkdir -p "$(dirname "$LOCK_FILE")"
  exec 9>"$LOCK_FILE"
  if ! flock -n 9; then
    die "another deploy holds $LOCK_FILE — aborting"
  fi
  log "acquired lock $LOCK_FILE"
}

prune_logs() {
  local logs
  shopt -s nullglob
  logs=("$LOG_DIR"/deploy-*.log)
  if ((${#logs[@]} > LOG_KEEP)); then
    printf '%s\n' "${logs[@]}" | sort | head -n -"$LOG_KEEP" | xargs -r rm -f
    log "pruned old deploy logs (keeping $LOG_KEEP)"
  fi
}

refresh_launcher() {
  local src="$DEPLOY_DIR/scripts/deploy-codex-lb.sh"
  local dest="${CODEX_LB_DEPLOY_LAUNCHER:-$HOME/bin/deploy-codex-lb.sh}"
  if [[ -f "$src" ]]; then
    mkdir -p "$(dirname "$dest")"
    install -m 755 "$src" "$dest"
    log "refreshed launcher -> $dest"
  else
    log "skip launcher refresh (no $src yet)"
  fi
}

wait_service_active() {
  local i state
  for ((i = 1; i <= ACTIVE_RETRIES; i++)); do
    state="$(systemctl --user is-active "$SERVICE" 2>/dev/null || true)"
    case "$state" in
      active)
        log "$SERVICE is active (attempt $i/$ACTIVE_RETRIES)"
        return 0
        ;;
      activating)
        log "$SERVICE activating (attempt $i/$ACTIVE_RETRIES)"
        ;;
      failed)
        die "$SERVICE entered failed state during startup"
        ;;
      *)
        log "$SERVICE state=$state (attempt $i/$ACTIVE_RETRIES)"
        ;;
    esac
    sleep 1
  done
  die "$SERVICE did not become active after ${ACTIVE_RETRIES}s (state=$(systemctl --user is-active "$SERVICE" 2>/dev/null || true))"
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

sync_git() {
  local current remote_sha
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
  remote_sha="$(git rev-parse "$REMOTE/$BRANCH")"
  log "REMOTE_SHA=$remote_sha"

  current="$(git rev-parse --abbrev-ref HEAD)"
  if [[ "$current" != "$BRANCH" ]]; then
    if [[ "$SWITCH_BRANCH" != "1" ]]; then
      die "deploy dir is on '$current', not '$BRANCH'. Use a dedicated clone, or set CODEX_LB_DEPLOY_SWITCH_BRANCH=1"
    fi
    log "switching $current -> $BRANCH (CODEX_LB_DEPLOY_SWITCH_BRANCH=1)"
    if git show-ref --verify --quiet "refs/heads/$BRANCH"; then
      git checkout "$BRANCH"
    else
      git checkout -b "$BRANCH" --track "$REMOTE/$BRANCH"
    fi
  fi

  log "fast-forward $BRANCH to $REMOTE/$BRANCH"
  git merge --ff-only "$REMOTE/$BRANCH"
}

log "=== codex-lb deploy start ==="
log "host=$(hostname) user=$(id -un) pid=$$"
log "DEPLOY_DIR=$DEPLOY_DIR"
log "SERVICE=$SERVICE BRANCH=$BRANCH REMOTE=$REMOTE"
log "LOG_FILE=$LOG_FILE"

require_int HEALTH_RETRIES "$HEALTH_RETRIES"
require_int HEALTH_SLEEP_SECS "$HEALTH_SLEEP_SECS"
require_int ACTIVE_RETRIES "$ACTIVE_RETRIES"
require_int LOG_KEEP "$LOG_KEEP"

acquire_lock
prune_logs

require_cmd git
require_cmd systemctl
require_cmd curl
require_cmd flock
require_cmd install
[[ -x "$UV_BIN" ]] || require_cmd uv "$UV_BIN"
if [[ "$SKIP_FRONTEND" != "1" ]]; then
  [[ -x "$BUN_BIN" ]] || require_cmd bun "$BUN_BIN"
fi

ensure_user_systemd

[[ -d "$DEPLOY_DIR" ]] || die "deploy dir missing: $DEPLOY_DIR"
[[ -d "$DEPLOY_DIR/.git" ]] || die "not a git repo: $DEPLOY_DIR"
cd "$DEPLOY_DIR"

sync_git

AFTER_SHA="$(git rev-parse HEAD)"
log "AFTER_SHA=$AFTER_SHA"
git log -1 --oneline

log "syncing Python deps (uv sync --frozen)"
"$UV_BIN" sync --frozen

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
  log "reloading user systemd units"
  systemctl --user daemon-reload
  log "restarting systemd user unit: $SERVICE"
  systemctl --user restart "$SERVICE"
  wait_service_active
  wait_healthy
  systemctl --user reset-failed "$SERVICE" >/dev/null 2>&1 || true
fi

log "=== codex-lb deploy success ==="
log "deployed $BEFORE_SHA -> $AFTER_SHA"
log "log: $LOG_FILE"
exit 0
