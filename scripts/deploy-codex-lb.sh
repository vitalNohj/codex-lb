#!/usr/bin/env bash
# Deploy codex-lb from origin/main and restart the systemd user service.
# Trigger: nohj.dev POST /hooks/github (push to main). Do not use a
# self-hosted Actions runner on this public repo.
#
# Env overrides:
#   CODEX_LB_DEPLOY_DIR            Install path (default: /home/nohj/personal/codex-lb)
#   CODEX_LB_SERVICE               systemd user unit (default: codex-lb.service)
#   CODEX_LB_DEPLOY_BRANCH         Branch to deploy (default: main)
#   CODEX_LB_DEPLOY_REMOTE         Git remote (default: origin)
#   CODEX_LB_DEPLOY_LOG_DIR        Log directory (default: ~/.local/state/codex-lb/deploy)
#   CODEX_LB_DEPLOY_LOCK           Lock file (default: $LOG_DIR/deploy.lock)
#   CODEX_LB_DEPLOY_LOCK_WAIT      Seconds to wait for a concurrent deploy to finish before
#                                  running (default 900: a merge that arrives while another
#                                  deploy runs is deployed right after it; 0 fails fast
#                                  instead of waiting)
#   CODEX_LB_DEPLOY_ALLOW_DIRTY    Set to 1 to allow uncommitted changes in place
#                                  (default: stash them first — see below)
#   CODEX_LB_DEPLOY_SWITCH_BRANCH  Set to 1 to checkout BRANCH when the clone is elsewhere
#   CODEX_LB_HEALTH_URL            Post-restart readiness probe (default:
#                                  http://127.0.0.1:<CODEX_LB_LISTEN port>/health/ready)
#   CODEX_LB_SERVICE_LAYOUT        socket (default) or single; see "Service layout" below.
#                                  Without it, the layout recorded by the last deploy is kept
#   CODEX_LB_SERVICE_LAYOUT_FILE   Records the layout in use (default: $LOG_DIR/service-layout)
#   CODEX_LB_SOCKET                systemd user socket unit (default: codex-lb.socket)
#   CODEX_LB_SYSTEMD_USER_DIR      Where the managed units go (default: ~/.config/systemd/user)
#   CODEX_LB_LISTEN                Address the socket unit holds (default: 0.0.0.0:2455)
#   CODEX_LB_DRAIN_TIMEOUT_SECONDS Drain budget for in-flight requests at a restart in the
#                                  socket layout (default: 120, at most 300)
#   CODEX_LB_DEPLOY_DATA_DIR       Optional CODEX_LB_DATA_DIR for the service (for a rehearsal copy)
#   CODEX_LB_VENV_DIR              Virtualenv the socket layout runs (default: $DEPLOY_DIR/.venv,
#                                  the one uv sync --frozen builds)
#   CODEX_LB_SKIP_FRONTEND         Set to 1 to skip bun install/build
#   CODEX_LB_FORCE_FRONTEND        Set to 1 to build the frontend even when frontend/
#                                  is unchanged since the last successful build (default:
#                                  skip the build when frontend/ is unchanged and
#                                  app/static/index.html already exists)
#   CODEX_LB_FRONTEND_STAMP        File recording the SHA of the last successful frontend
#                                  build (default: $LOG_DIR/frontend-built.sha). Missing
#                                  stamp forces a build.
#   CODEX_LB_SKIP_RESTART          Set to 1 to pull/build only (no systemd restart)
#   CODEX_LB_DEPLOY_LAUNCHER       Path to refresh after a successful pull
#
# Local-state safety (never discards work): if the deploy clone is dirty, or
# its BRANCH has commits not on REMOTE/BRANCH (ahead or diverged), the script
# preserves that state BEFORE touching anything — a branch
# backup/deploy-preserved-<UTC stamp> is created at the tip of the branch
# being reset (a detached pre-checkout HEAD gets a
# backup/deploy-preserved-<UTC stamp>-pre branch before the checkout) and a
# dirty tree is stashed with message deploy-preserved-<UTC stamp>
# (--include-untracked) — and everything preserved is logged. Ignored files
# that the incoming tree would silently overwrite are moved aside to
# ignored-preserved-<UTC stamp>/ under the log dir. Then the branch
# is reset to REMOTE/BRANCH and the deploy continues, so every merge deploys
# and no local work is lost. With CODEX_LB_DEPLOY_ALLOW_DIRTY=1 the script
# keeps uncommitted changes in place instead and still refuses (loudly) to
# leave HEAD off REMOTE/BRANCH.
#
# Service layout. In the socket layout, a socket unit (CODEX_LB_SOCKET) holds
# the listening port, and a managed drop-in makes the service serve that
# socket. At a restart, the old process stops accepting, finishes its
# in-flight requests within CODEX_LB_DRAIN_TIMEOUT_SECONDS and exits; new
# connections wait in the kernel queue for the new process instead of being
# refused. The script never edits the service unit itself; it only writes
#   <unit dir>/<socket unit>
#   <unit dir>/<service>.d/50-socket-handoff.conf
# The first deploy in the socket layout stops the service, starts the socket
# and starts the service again. If that fails, or the service does not become
# ready on the socket, the script removes both files, starts the service as
# before, records the single layout and fails loudly.
#
# Rollback to the single unit (one command; restarts the service):
#   deploy-codex-lb.sh rollback-layout
# It needs no git access and records the single layout, so later deploys
# keep the single unit until CODEX_LB_SERVICE_LAYOUT=socket is set again.
#
set -euo pipefail

COMMAND="${1:-deploy}"
case "$COMMAND" in
  deploy | rollback-layout) ;;
  *)
    printf 'usage: %s [deploy|rollback-layout]\n' "$0" >&2
    exit 2
    ;;
esac

DEPLOY_DIR="${CODEX_LB_DEPLOY_DIR:-/home/nohj/personal/codex-lb}"
SERVICE="${CODEX_LB_SERVICE:-codex-lb.service}"
BRANCH="${CODEX_LB_DEPLOY_BRANCH:-main}"
REMOTE="${CODEX_LB_DEPLOY_REMOTE:-origin}"
LOG_DIR="${CODEX_LB_DEPLOY_LOG_DIR:-${XDG_STATE_HOME:-$HOME/.local/state}/codex-lb/deploy}"
LOCK_FILE="${CODEX_LB_DEPLOY_LOCK:-$LOG_DIR/deploy.lock}"
LOCK_WAIT="${CODEX_LB_DEPLOY_LOCK_WAIT:-900}"
ALLOW_DIRTY="${CODEX_LB_DEPLOY_ALLOW_DIRTY:-0}"
SWITCH_BRANCH="${CODEX_LB_DEPLOY_SWITCH_BRANCH:-0}"
LISTEN="${CODEX_LB_LISTEN:-0.0.0.0:2455}"
LISTEN_PORT="${LISTEN##*:}"
HEALTH_URL="${CODEX_LB_HEALTH_URL:-http://127.0.0.1:${LISTEN_PORT}/health/ready}"
LAYOUT_REQUEST="${CODEX_LB_SERVICE_LAYOUT:-}"
SOCKET="${CODEX_LB_SOCKET:-codex-lb.socket}"
UNIT_DIR="${CODEX_LB_SYSTEMD_USER_DIR:-${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user}"
DRAIN_SECS="${CODEX_LB_DRAIN_TIMEOUT_SECONDS:-120}"
SERVICE_DATA_DIR="${CODEX_LB_DEPLOY_DATA_DIR:-}"
VENV_DIR="${CODEX_LB_VENV_DIR:-$DEPLOY_DIR/.venv}"
SKIP_FRONTEND="${CODEX_LB_SKIP_FRONTEND:-0}"
FORCE_FRONTEND="${CODEX_LB_FORCE_FRONTEND:-0}"
STAMP_FILE="${CODEX_LB_FRONTEND_STAMP:-$LOG_DIR/frontend-built.sha}"
SKIP_RESTART="${CODEX_LB_SKIP_RESTART:-0}"
HEALTH_RETRIES="${CODEX_LB_HEALTH_RETRIES:-45}"
HEALTH_SLEEP_SECS="${CODEX_LB_HEALTH_SLEEP_SECS:-2}"
ACTIVE_RETRIES="${CODEX_LB_ACTIVE_RETRIES:-30}"
LOG_KEEP="${CODEX_LB_DEPLOY_LOG_KEEP:-20}"

UV_BIN="${UV_BIN:-$HOME/.local/bin/uv}"
BUN_BIN="${BUN_BIN:-$HOME/.bun/bin/bun}"
# systemd-run PATH is often /usr/bin:/bin. bun run build shells out to `bun`.
export PATH="$(dirname -- "$BUN_BIN"):$PATH"
TS="$(date -u +%Y%m%dT%H%M%SZ)"
LOG_FILE="$LOG_DIR/deploy-$TS.log"
LAYOUT_FILE="${CODEX_LB_SERVICE_LAYOUT_FILE:-$LOG_DIR/service-layout}"
SOCKET_FILE="$UNIT_DIR/$SOCKET"
DROPIN_FILE="$UNIT_DIR/$SERVICE.d/50-socket-handoff.conf"
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
  log "SWITCH_BRANCH=$SWITCH_BRANCH SKIP_FRONTEND=$SKIP_FRONTEND FORCE_FRONTEND=$FORCE_FRONTEND SKIP_RESTART=$SKIP_RESTART"
  log "STAMP_FILE=$STAMP_FILE"
  log "HEALTH_URL=$HEALTH_URL"
  log "SOCKET=$SOCKET LISTEN=$LISTEN UNIT_DIR=$UNIT_DIR layout=$(recorded_layout)"
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
  log "=== codex-lb deploy failed ==="
  exit 1
}

on_err() {
  local exit_code=$?
  local line=${1:-?}
  log "FAILED at line ${line} (exit ${exit_code})"
  dump_diagnostics
  log "=== codex-lb deploy failed ==="
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
  local waited_from=$SECONDS
  mkdir -p "$(dirname "$LOCK_FILE")"
  exec 9>"$LOCK_FILE"
  if flock -n 9; then
    log "acquired lock $LOCK_FILE"
    return 0
  fi
  if ((LOCK_WAIT <= 0)); then
    die "another deploy holds $LOCK_FILE — aborting (set CODEX_LB_DEPLOY_LOCK_WAIT>0 to queue behind it)"
  fi
  log "another deploy holds $LOCK_FILE — waiting up to ${LOCK_WAIT}s so this push deploys right after the current one"
  if ! flock -w "$LOCK_WAIT" 9; then
    die "another deploy still held $LOCK_FILE after waiting ${LOCK_WAIT}s — this push has NOT been deployed; inspect the running deploy, then re-run"
  fi
  log "acquired lock $LOCK_FILE (waited $((SECONDS - waited_from))s for the previous deploy to finish)"
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

# --- service layout (see "Service layout" in the header) ---------------------

recorded_layout() {
  if [[ -f "$LAYOUT_FILE" ]]; then
    tr -d '[:space:]' <"$LAYOUT_FILE"
  fi
}

record_layout() {
  mkdir -p "$(dirname "$LAYOUT_FILE")"
  printf '%s\n' "$1" >"$LAYOUT_FILE.tmp"
  mv -f "$LAYOUT_FILE.tmp" "$LAYOUT_FILE"
  log "recorded service layout '$1' -> $LAYOUT_FILE"
}

# Set LAYOUT from CODEX_LB_SERVICE_LAYOUT, else the recorded layout, else socket.
resolve_layout() {
  LAYOUT=$LAYOUT_REQUEST
  if [[ -z "$LAYOUT" ]]; then
    LAYOUT="$(recorded_layout)"
  fi
  LAYOUT="${LAYOUT:-socket}"
  case "$LAYOUT" in
    socket | single) ;;
    *) die "service layout must be 'socket' or 'single' (got ${LAYOUT@Q})" ;;
  esac
}

unit_safe_path() {
  local name=$1
  local value=$2
  # Unit files treat whitespace, quotes, backslashes and % specially.
  if [[ "$value" != /* || "$value" =~ [[:space:]\"\'\\%] ]]; then
    die "$name must be an absolute path without spaces, quotes, backslashes or % for the socket layout (got ${value@Q})"
  fi
}

socket_unit_text() {
  cat <<EOF
# Managed by scripts/deploy-codex-lb.sh (socket layout). Do not edit by hand.
# Rollback to the single unit: deploy-codex-lb.sh rollback-layout
[Unit]
Description=codex-lb listening socket (held across $SERVICE restarts)

[Socket]
ListenStream=$LISTEN
Service=$SERVICE
Backlog=4096
NoDelay=true

[Install]
WantedBy=sockets.target
EOF
}

service_dropin_text() {
  local manager_path
  manager_path="$(systemctl --user show-environment 2>/dev/null | sed -n 's/^PATH=//p')"
  manager_path="${manager_path:-/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin}"
  cat <<EOF
# Managed by scripts/deploy-codex-lb.sh (socket layout). Do not edit by hand.
# Rollback to the single unit: deploy-codex-lb.sh rollback-layout
[Unit]
Requires=$SOCKET
After=$SOCKET

[Service]
# Run the console script directly: \`uv run\` forks a child process, and
# systemd passes the socket only to the main process (LISTEN_PID).
ExecStart=
ExecStart=$VENV_DIR/bin/codex-lb --host ${LISTEN%:*} --port $LISTEN_PORT
Environment=VIRTUAL_ENV=$VENV_DIR
Environment=PATH=$VENV_DIR/bin:$manager_path
Environment=CODEX_LB_SHUTDOWN_DRAIN_TIMEOUT_SECONDS=$DRAIN_SECS
TimeoutStopSec=$((DRAIN_SECS + 60))
EOF
  if [[ -n "$SERVICE_DATA_DIR" ]]; then
    printf 'Environment=CODEX_LB_DATA_DIR=%s\n' "$SERVICE_DATA_DIR"
  fi
}

# Write $2 to $1 only when it differs; return 0 when the file changed.
write_if_changed() {
  local path=$1
  local text=$2
  if [[ -f "$path" ]] && [[ "$(cat "$path")" == "$text" ]]; then
    return 1
  fi
  mkdir -p "$(dirname "$path")"
  printf '%s\n' "$text" >"$path.tmp"
  mv -f "$path.tmp" "$path"
  log "wrote $path"
  return 0
}

unit_is_active() {
  [[ "$(systemctl --user is-active "$1" 2>/dev/null || true)" == "active" ]]
}

# Return to the single unit: drain and stop the service, release the port,
# remove the managed files and start the service on its own again.
remove_socket_layout() {
  log "stopping $SERVICE and $SOCKET to leave the socket layout"
  systemctl --user stop "$SOCKET" "$SERVICE" || true
  systemctl --user disable "$SOCKET" >/dev/null 2>&1 || true
  rm -f "$SOCKET_FILE" "$DROPIN_FILE"
  rmdir "$(dirname "$DROPIN_FILE")" 2>/dev/null || true
  log "removed $SOCKET_FILE and $DROPIN_FILE"
  systemctl --user daemon-reload
  systemctl --user reset-failed "$SOCKET" "$SERVICE" >/dev/null 2>&1 || true
  log "starting $SERVICE as a single unit"
  systemctl --user start "$SERVICE"
}

socket_layout_present() {
  [[ -e "$SOCKET_FILE" || -e "$DROPIN_FILE" ]] || unit_is_active "$SOCKET"
}

# The socket layout failed to come up: go back to the single unit so the
# service keeps running the deployed code, then fail the deploy loudly.
fall_back_to_single() {
  local reason=$1
  log "ERROR: socket layout failed: $reason"
  log "falling back to the single unit"
  remove_socket_layout
  record_layout single
  if wait_service_active && wait_healthy; then
    die "socket layout failed ($reason); $SERVICE runs as a single unit again. Fix the cause, then deploy with CODEX_LB_SERVICE_LAYOUT=socket"
  fi
  die "socket layout failed ($reason) and $SERVICE did not come back as a single unit"
}

restart_single_layout() {
  if socket_layout_present; then
    log "service layout 'single' requested; removing the socket layout"
    remove_socket_layout
  else
    log "restarting systemd user unit: $SERVICE"
    systemctl --user daemon-reload
    systemctl --user restart "$SERVICE"
  fi
  record_layout single
  wait_service_active
  wait_healthy
}

restart_socket_layout() {
  local socket_text dropin_text socket_changed=0
  unit_safe_path CODEX_LB_VENV_DIR "$VENV_DIR"
  [[ -z "$SERVICE_DATA_DIR" ]] || unit_safe_path CODEX_LB_DEPLOY_DATA_DIR "$SERVICE_DATA_DIR"
  [[ -x "$VENV_DIR/bin/codex-lb" ]] || die "socket layout needs $VENV_DIR/bin/codex-lb (run uv sync --frozen); $SERVICE was not touched"
  "$VENV_DIR/bin/codex-lb" --help >/dev/null 2>&1 || die "$VENV_DIR/bin/codex-lb --help failed; $SERVICE was not touched"

  socket_text="$(socket_unit_text)"
  dropin_text="$(service_dropin_text)"
  if write_if_changed "$SOCKET_FILE" "$socket_text"; then
    socket_changed=1
  fi
  write_if_changed "$DROPIN_FILE" "$dropin_text" || true
  systemctl --user daemon-reload

  if [[ "$socket_changed" == "0" ]] && unit_is_active "$SOCKET"; then
    # Steady state: the socket keeps the port. The old process stops
    # accepting, finishes in-flight requests, and the new one takes the queue.
    log "restarting $SERVICE; $SOCKET holds the port during the drain (up to ${DRAIN_SECS}s)"
    systemctl --user restart "$SERVICE"
    record_layout socket
    wait_service_active
    wait_healthy
    return 0
  fi

  # Move to the socket layout (or apply a changed socket unit). The running
  # process owns the port, so it must stop before the socket can bind it.
  log "moving $SERVICE to the socket layout: stop $SERVICE, start $SOCKET, start $SERVICE"
  systemctl --user stop "$SERVICE" || fall_back_to_single "could not stop $SERVICE"
  if unit_is_active "$SOCKET"; then
    systemctl --user stop "$SOCKET" || fall_back_to_single "could not stop $SOCKET"
  fi
  systemctl --user start "$SOCKET" || fall_back_to_single "could not start $SOCKET on $LISTEN"
  systemctl --user enable "$SOCKET" >/dev/null 2>&1 || fall_back_to_single "could not enable $SOCKET"
  systemctl --user start "$SERVICE" || fall_back_to_single "could not start $SERVICE on $SOCKET"
  local i state ready=0
  for ((i = 1; i <= HEALTH_RETRIES; i++)); do
    state="$(systemctl --user is-active "$SERVICE" 2>/dev/null || true)"
    if [[ "$state" == "failed" ]]; then
      break
    fi
    if [[ "$state" == "active" ]] && curl -fsS --max-time 3 "$HEALTH_URL" >/dev/null 2>&1; then
      ready=1
      break
    fi
    log "waiting for $SERVICE to become ready on $SOCKET ($i/$HEALTH_RETRIES, state=$state) $HEALTH_URL"
    sleep "$HEALTH_SLEEP_SECS"
  done
  if [[ "$ready" != "1" ]]; then
    fall_back_to_single "$SERVICE did not become ready at $HEALTH_URL on $SOCKET"
  fi
  log "health check OK ($HEALTH_URL); $SERVICE serves $SOCKET"
  record_layout socket
}

rollback_layout() {
  log "=== codex-lb service layout rollback start ==="
  acquire_lock
  require_cmd systemctl
  require_cmd curl
  require_cmd flock
  ensure_user_systemd
  if socket_layout_present; then
    remove_socket_layout
  else
    log "no socket layout found ($SOCKET_FILE, $DROPIN_FILE); $SERVICE already runs as a single unit"
  fi
  record_layout single
  wait_service_active
  wait_healthy
  systemctl --user reset-failed "$SERVICE" >/dev/null 2>&1 || true
  log "=== codex-lb service layout rollback success ==="
  log "later deploys keep the single unit; set CODEX_LB_SERVICE_LAYOUT=socket to go back"
  log "log: $LOG_FILE"
}

stash_dirty_tree() {
  local msg="deploy-preserved-$TS"
  local stashed
  if ! stashed="$(git stash push --include-untracked -m "$msg")"; then
    die "working tree was dirty but 'git stash push' failed — refusing to continue; nothing was discarded"
  fi
  log "PRESERVED dirty working tree: stash '${stashed}' (message: $msg)"
  local stash_files
  if stash_files="$(git stash show --include-untracked --name-status "stash@{0}" 2>/dev/null)"; then
    [[ -z "$stash_files" ]] || printf '%s\n' "$stash_files" | sed 's/^/  stashed: /'
  fi
}

preserve_local_commits() {
  local old_sha=$1
  local backup_branch="backup/deploy-preserved-$TS"
  git branch "$backup_branch" "$old_sha"
  log "PRESERVED local commits: branch $backup_branch at $old_sha (the reset below will not discard them)"
  git log --oneline --no-decorate "$old_sha" --not "$REMOTE/$BRANCH" | sed 's/^/  preserved: /'
}

# Ignored files are expendable to git: a checkout/merge/reset that brings in
# a tracked file at the same path silently overwrites them (an ignored file
# never shows up in `git status --porcelain`, so the stash above never sees
# it). Move any that collide with REMOTE/BRANCH's tree aside — never discard.
protect_ignored_files() {
  local target_tree="$1"
  local ignored_dir="$LOG_DIR/ignored-preserved-$TS"
  local ignored target_files collisions path dest
  ignored="$(git -c core.quotePath=false ls-files --others -i --exclude-standard | sort)" ||
    die "cannot list ignored files — refusing to update the tree (reset/merge could overwrite them)"
  target_files="$(git -c core.quotePath=false ls-tree -r --name-only "$target_tree" | sort)" ||
    die "cannot list $target_tree — refusing to update the tree (reset/merge could overwrite ignored files)"
  [[ -z "$ignored" || -z "$target_files" ]] && return 0
  collisions="$(comm -12 <(printf '%s\n' "$ignored") <(printf '%s\n' "$target_files") || true)"
  [[ -z "$collisions" ]] && return 0
  mkdir -p "$ignored_dir"
  while IFS= read -r path; do
    [[ -n "$path" && (-e "$path" || -L "$path") ]] || continue
    dest="$ignored_dir/$path"
    mkdir -p -- "$(dirname -- "$dest")"
    mv -- "$path" "$dest"
    log "PRESERVED ignored file in the way of the target tree: $path -> $dest"
  done <<<"$collisions"
}

sync_git() {
  local current remote_sha ahead behind branch_tip dirty=0 preserved=0
  log "pre-deploy git state:"
  git status --short --branch
  BEFORE_SHA="$(git rev-parse HEAD)"
  log "BEFORE_SHA=$BEFORE_SHA"

  if [[ -n "$(git status --porcelain)" ]]; then
    dirty=1
  fi

  log "fetching $REMOTE $BRANCH"
  git fetch --prune "$REMOTE" "$BRANCH"
  remote_sha="$(git rev-parse "$REMOTE/$BRANCH")"
  log "REMOTE_SHA=$remote_sha"

  # Refuse states this run cannot converge on BEFORE touching the working
  # tree: every die below leaves the deploy dir exactly as it was found.
  current="$(git rev-parse --abbrev-ref HEAD)"
  if [[ "$current" != "$BRANCH" && "$SWITCH_BRANCH" != "1" ]]; then
    die "deploy dir is on '$current', not '$BRANCH'. Use a dedicated clone, or set CODEX_LB_DEPLOY_SWITCH_BRANCH=1"
  fi

  local counts
  if git show-ref --verify --quiet "refs/heads/$BRANCH"; then
    if ! counts="$(git rev-list --left-right --count "$BRANCH...$REMOTE/$BRANCH")"; then
      die "cannot compare $BRANCH with $REMOTE/$BRANCH — is the branch deleted on $REMOTE? refusing to guess the deploy state"
    fi
    read -r ahead behind <<<"$counts"
  else
    # No local $BRANCH yet: the checkout below creates it from $REMOTE/$BRANCH,
    # so there is nothing local to preserve or refuse.
    ahead=0
    behind=0
  fi

  if ((ahead > 0)) && [[ "$ALLOW_DIRTY" == "1" ]]; then
    die "local $BRANCH is ahead of $REMOTE/$BRANCH by $ahead commit(s) and CODEX_LB_DEPLOY_ALLOW_DIRTY=1 keeps local changes in place — the deploy cannot converge; push or rebase the ahead commits, then re-run"
  fi

  # Every refusal cleared. Preserve local state first, then mutate.
  if ((dirty)) && [[ "$ALLOW_DIRTY" != "1" ]]; then
    log "working tree dirty under $DEPLOY_DIR — preserving it before deploying"
    stash_dirty_tree
    preserved=1
  elif ((dirty)); then
    log "working tree dirty under $DEPLOY_DIR (CODEX_LB_DEPLOY_ALLOW_DIRTY=1: keeping uncommitted changes in place)"
  fi

  protect_ignored_files "$REMOTE/$BRANCH"

  if [[ "$current" != "$BRANCH" ]]; then
    # A named branch keeps its commits reachable through the checkout, but a
    # detached HEAD does not — back it up before leaving it.
    if [[ "$current" == "HEAD" ]]; then
      git branch "backup/deploy-preserved-$TS-pre" "$BEFORE_SHA"
      log "PRESERVED detached HEAD: branch backup/deploy-preserved-$TS-pre at $BEFORE_SHA (before switching to $BRANCH)"
    fi
    log "switching $current -> $BRANCH (CODEX_LB_DEPLOY_SWITCH_BRANCH=1)"
    if git show-ref --verify --quiet "refs/heads/$BRANCH"; then
      git checkout "$BRANCH"
    else
      git checkout -b "$BRANCH" --track "$REMOTE/$BRANCH"
    fi
  fi

  # The reset below moves $BRANCH, so back up ITS tip — not BEFORE_SHA: with
  # CODEX_LB_DEPLOY_SWITCH_BRANCH=1, BEFORE_SHA is the pre-checkout ref's tip
  # (kept reachable by its own branch), and backing that up instead would let
  # the reset drop local $BRANCH commits. The checkout above never moves
  # refs, so the ahead/behind counts validated earlier still hold.
  branch_tip="$(git rev-parse HEAD)"
  if ((ahead > 0)) && [[ "$ALLOW_DIRTY" != "1" ]]; then
    log "local $BRANCH has $ahead commit(s) not on $REMOTE/$BRANCH (ahead=$ahead behind=$behind) — preserving before reset"
    preserve_local_commits "$branch_tip"
    preserved=1
  fi

  if ((preserved)); then
    log "resetting $BRANCH to $REMOTE/$BRANCH ($remote_sha)"
    git reset --hard "$REMOTE/$BRANCH"
  else
    log "fast-forward $BRANCH to $REMOTE/$BRANCH"
    git merge --ff-only "$REMOTE/$BRANCH"
  fi

  if [[ "$(git rev-parse HEAD)" != "$remote_sha" ]]; then
    die "deploy dir HEAD $(git rev-parse HEAD) does not match $REMOTE/$BRANCH ($remote_sha) after sync — deploy aborted"
  fi
}

# Prints "changed" or "unchanged" for frontend/ between the last successfully
# built SHA (from STAMP_FILE) and AFTER_SHA. The baseline is the stamp, not the
# pre-pull HEAD: sync_git moves HEAD to REMOTE/BRANCH before the build, so a
# failed or skipped build must not let the next run skip the rebuild. Missing/empty stamp,
# uncommitted edits under frontend/ (reachable with ALLOW_DIRTY=1), or any git
# error (including an invalid SHA) count as changed so a bad baseline can never
# skip a needed build. Diagnostics go to stderr because the caller captures
# stdout.
frontend_dirty() {
  local status rc=0
  status="$(git status --porcelain -- frontend/ 2>/dev/null)" || rc=$?
  ((rc != 0)) || [[ -n "$status" ]]
}

frontend_change_state() {
  local stamp="" rc=0
  if [[ -s "$STAMP_FILE" ]]; then
    stamp="$(tr -d '[:space:]' <"$STAMP_FILE")"
  fi
  log "frontend baseline: ${stamp:-none} ($STAMP_FILE)" >&2
  if [[ -z "$stamp" ]]; then
    echo changed
    return 0
  fi
  if frontend_dirty; then
    log "frontend/ has uncommitted changes; treating as changed" >&2
    echo changed
    return 0
  fi
  if [[ "$stamp" == "$AFTER_SHA" ]]; then
    echo unchanged
    return 0
  fi
  git diff --quiet "$stamp" "$AFTER_SHA" -- frontend/ 2>/dev/null || rc=$?
  if ((rc == 0)); then
    echo unchanged
  else
    echo changed
  fi
}

build_frontend() {
  log "installing frontend deps (bun install --frozen-lockfile)"
  (
    cd frontend
    "$BUN_BIN" install --frozen-lockfile
    log "building frontend (bun run build) -> app/static"
    "$BUN_BIN" run build
  )
  [[ -f app/static/index.html ]] || die "frontend build missing app/static/index.html"
  if frontend_dirty; then
    # The bundle includes uncommitted edits, so AFTER_SHA does not describe it.
    # Drop the stamp so the next deploy rebuilds even at the same HEAD.
    rm -f "$STAMP_FILE"
    log "frontend/ was dirty at build time; not recording build stamp"
    return 0
  fi
  printf '%s\n' "$AFTER_SHA" >"$STAMP_FILE.tmp"
  mv -f "$STAMP_FILE.tmp" "$STAMP_FILE"
  log "recorded frontend build stamp $AFTER_SHA -> $STAMP_FILE"
}

require_int HEALTH_RETRIES "$HEALTH_RETRIES"
require_int HEALTH_SLEEP_SECS "$HEALTH_SLEEP_SECS"
require_int ACTIVE_RETRIES "$ACTIVE_RETRIES"
require_int CODEX_LB_DRAIN_TIMEOUT_SECONDS "$DRAIN_SECS"
((DRAIN_SECS <= 300)) || die "CODEX_LB_DRAIN_TIMEOUT_SECONDS must be at most 300 (got $DRAIN_SECS)"
[[ "$LISTEN" =~ ^[^[:space:]]+:[1-9][0-9]*$ ]] || die "CODEX_LB_LISTEN must be <host>:<port> (got ${LISTEN@Q})"

if [[ "$COMMAND" == "rollback-layout" ]]; then
  rollback_layout
  exit 0
fi

log "=== codex-lb deploy start ==="
log "host=$(hostname) user=$(id -un) pid=$$"
log "DEPLOY_DIR=$DEPLOY_DIR"
log "SERVICE=$SERVICE BRANCH=$BRANCH REMOTE=$REMOTE"
log "LOG_FILE=$LOG_FILE"

require_int LOG_KEEP "$LOG_KEEP"
[[ "$LOCK_WAIT" =~ ^[0-9]+$ ]] || die "CODEX_LB_DEPLOY_LOCK_WAIT must be a non-negative integer (got ${LOCK_WAIT@Q})"

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

if [[ "$SKIP_FRONTEND" == "1" ]]; then
  log "skipping frontend (CODEX_LB_SKIP_FRONTEND=1)"
elif [[ "$FORCE_FRONTEND" == "1" ]]; then
  log "forcing frontend build (CODEX_LB_FORCE_FRONTEND=1)"
  build_frontend
elif [[ "$(frontend_change_state)" == "unchanged" && -f app/static/index.html ]]; then
  log "skipping frontend build (no changes in frontend/ since last successful build)"
else
  build_frontend
fi

refresh_launcher

if [[ "$SKIP_RESTART" == "1" ]]; then
  log "skipping restart (CODEX_LB_SKIP_RESTART=1)"
else
  resolve_layout
  log "service layout: $LAYOUT"
  if [[ "$LAYOUT" == "socket" ]]; then
    restart_socket_layout
  else
    restart_single_layout
  fi
  systemctl --user reset-failed "$SERVICE" >/dev/null 2>&1 || true
fi

log "=== codex-lb deploy success ==="
log "deployed $BEFORE_SHA -> $AFTER_SHA"
log "log: $LOG_FILE"
exit 0
