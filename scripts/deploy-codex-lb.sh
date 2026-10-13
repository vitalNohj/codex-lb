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
#   CODEX_LB_HEALTH_URL            Post-restart probe (default: http://127.0.0.1:2455/health/live)
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
set -euo pipefail

DEPLOY_DIR="${CODEX_LB_DEPLOY_DIR:-/home/nohj/personal/codex-lb}"
SERVICE="${CODEX_LB_SERVICE:-codex-lb.service}"
BRANCH="${CODEX_LB_DEPLOY_BRANCH:-main}"
REMOTE="${CODEX_LB_DEPLOY_REMOTE:-origin}"
LOG_DIR="${CODEX_LB_DEPLOY_LOG_DIR:-${XDG_STATE_HOME:-$HOME/.local/state}/codex-lb/deploy}"
LOCK_FILE="${CODEX_LB_DEPLOY_LOCK:-$LOG_DIR/deploy.lock}"
LOCK_WAIT="${CODEX_LB_DEPLOY_LOCK_WAIT:-900}"
ALLOW_DIRTY="${CODEX_LB_DEPLOY_ALLOW_DIRTY:-0}"
SWITCH_BRANCH="${CODEX_LB_DEPLOY_SWITCH_BRANCH:-0}"
HEALTH_URL="${CODEX_LB_HEALTH_URL:-http://127.0.0.1:2455/health/live}"
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

  if ((dirty)) && [[ "$ALLOW_DIRTY" != "1" ]]; then
    log "working tree dirty under $DEPLOY_DIR — preserving it before deploying"
    stash_dirty_tree
    preserved=1
  elif ((dirty)); then
    log "working tree dirty under $DEPLOY_DIR (CODEX_LB_DEPLOY_ALLOW_DIRTY=1: keeping uncommitted changes in place)"
  fi

  log "fetching $REMOTE $BRANCH"
  git fetch --prune "$REMOTE" "$BRANCH"
  remote_sha="$(git rev-parse "$REMOTE/$BRANCH")"
  log "REMOTE_SHA=$remote_sha"

  current="$(git rev-parse --abbrev-ref HEAD)"
  if [[ "$current" != "$BRANCH" && "$SWITCH_BRANCH" != "1" ]]; then
    die "deploy dir is on '$current', not '$BRANCH'. Use a dedicated clone, or set CODEX_LB_DEPLOY_SWITCH_BRANCH=1"
  fi

  # Only mutate the working tree once every refusal above has been cleared.
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
  # the reset drop local $BRANCH commits.
  branch_tip="$(git rev-parse HEAD)"

  local counts
  if ! counts="$(git rev-list --left-right --count "$BRANCH...$REMOTE/$BRANCH")"; then
    die "cannot compare $BRANCH with $REMOTE/$BRANCH — is the branch deleted on $REMOTE? refusing to guess the deploy state"
  fi
  read -r ahead behind <<<"$counts"
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

log "=== codex-lb deploy start ==="
log "host=$(hostname) user=$(id -un) pid=$$"
log "DEPLOY_DIR=$DEPLOY_DIR"
log "SERVICE=$SERVICE BRANCH=$BRANCH REMOTE=$REMOTE"
log "LOG_FILE=$LOG_FILE"

require_int HEALTH_RETRIES "$HEALTH_RETRIES"
require_int HEALTH_SLEEP_SECS "$HEALTH_SLEEP_SECS"
require_int ACTIVE_RETRIES "$ACTIVE_RETRIES"
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
