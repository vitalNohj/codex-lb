#!/bin/bash
# Child entry for the opt-in cross-language CLIProxyAPI HTTP contract.
# Do not invoke directly. Use the sandbox-exec command documented in README.md.
set -u
set -o pipefail
umask 077

fail() { echo "PREFLIGHT_FAIL: $*" >&2; exit 91; }
wait_owned() { local pid="$1"; wait "$pid"; }
group_exists() { /bin/kill -0 "-$1" 2>/dev/null; }
wait_group_empty() {
  local pid="$1" attempts=20
  while group_exists "$pid"; do
    attempts=$((attempts - 1))
    [ "$attempts" -gt 0 ] || return 1
    /bin/sleep 0.05
  done
}
stop_group() {
  local label="$1" pid="$2"
  if ! group_exists "$pid"; then
    echo "GROUP_ABSENT=$label:$pid" >> "$RUN_ROOT/evidence/exits.txt"
    return 0
  fi
  if ! /bin/kill -TERM "-$pid" 2>/dev/null; then
    if group_exists "$pid"; then
      echo "GROUP_TERM_ERROR=$label:$pid" >> "$RUN_ROOT/evidence/exits.txt"
      return 1
    fi
    echo "GROUP_ABSENT_AFTER_TERM=$label:$pid" >> "$RUN_ROOT/evidence/exits.txt"
    return 0
  fi
  if wait_group_empty "$pid"; then
    echo "GROUP_TERM_CONFIRMED=$label:$pid" >> "$RUN_ROOT/evidence/exits.txt"
    return 0
  fi
  if ! /bin/kill -KILL "-$pid" 2>/dev/null; then
    if group_exists "$pid"; then
      echo "GROUP_KILL_ERROR=$label:$pid" >> "$RUN_ROOT/evidence/exits.txt"
      return 1
    fi
  fi
  if wait_group_empty "$pid"; then
    echo "GROUP_KILL_CONFIRMED=$label:$pid" >> "$RUN_ROOT/evidence/exits.txt"
    return 0
  fi
  echo "GROUP_STILL_PRESENT=$label:$pid" >> "$RUN_ROOT/evidence/exits.txt"
  return 1
}

COMPILE_STAGE_PID=""
COMPILE_REAPED=0
GO_STAGE_PID=""
GO_REAPED=0
PY_STAGE_PID=""
PY_REAPED=0
cleanup() {
  local requested_status="$1" cleanup_failed=0 child_rc
  trap - EXIT INT TERM
  if [ -n "$PY_STAGE_PID" ]; then
    stop_group python "$PY_STAGE_PID" || cleanup_failed=1
    if [ "$PY_REAPED" -eq 0 ]; then
      wait_owned "$PY_STAGE_PID"; child_rc=$?
      echo "PYTHON_CLEANUP_EXIT=$child_rc" >> "$RUN_ROOT/evidence/exits.txt"
      PY_REAPED=1
    fi
    group_exists "$PY_STAGE_PID" && cleanup_failed=1
  fi
  if [ -n "$GO_STAGE_PID" ]; then
    stop_group fixture "$GO_STAGE_PID" || cleanup_failed=1
    if [ "$GO_REAPED" -eq 0 ]; then
      wait_owned "$GO_STAGE_PID"; child_rc=$?
      echo "GO_FIXTURE_CLEANUP_EXIT=$child_rc" >> "$RUN_ROOT/evidence/exits.txt"
      GO_REAPED=1
    fi
    group_exists "$GO_STAGE_PID" && cleanup_failed=1
  fi
  if [ -n "$COMPILE_STAGE_PID" ]; then
    stop_group compile "$COMPILE_STAGE_PID" || cleanup_failed=1
    if [ "$COMPILE_REAPED" -eq 0 ]; then
      wait_owned "$COMPILE_STAGE_PID"; child_rc=$?
      echo "GO_COMPILE_CLEANUP_EXIT=$child_rc" >> "$RUN_ROOT/evidence/exits.txt"
      COMPILE_REAPED=1
    fi
    group_exists "$COMPILE_STAGE_PID" && cleanup_failed=1
  fi
  if [ "$cleanup_failed" -ne 0 ]; then
    echo "CLEANUP_CONFIRMED=0" >> "$RUN_ROOT/evidence/exits.txt"
    [ "$requested_status" -ne 0 ] || requested_status=92
  else
    echo "CLEANUP_CONFIRMED=1" >> "$RUN_ROOT/evidence/exits.txt"
  fi
  exit "$requested_status"
}
on_exit() { local status=$?; cleanup "$status"; }
on_interrupt() { cleanup 130; }
on_terminate() { cleanup 143; }

PINNED_COMMIT=856ddd8df746a38a6033dbbf6c140974bf5aea0f
GO_BACKING_SHA=d57345a711547a91d2fe60c0408d8bf6891a6d4ac62efe39a62451203842e76b
PY_BACKING_SHA=97028fae6402f85eff54d5953b06a7166002191fd5828ccebc67e09b63f99ff2
PYTEST_CONFIG_SHA=204f9e5e80fecfa00cc5c996ebd64b4207ea9d3dae5cd63159927d5f6b7e9586
[ "${CODEX_LB_HTTP_LAUNCH:-}" = 1 ] || fail "use the documented sandbox invocation"
for name in CLIPROXY_SOURCE CLIPROXY_GIT GO_MODCACHE CODEX_LB_REPO GO_BIN TIMEOUT_BIN PYTHON_VENV PYTHON_TARGET PYVENV_CFG PYTHON_SITE_PACKAGES RUN_PARENT FIXTURE_PORT EDITABLE_PTH; do
  [ -n "${!name:-}" ] || fail "$name is required"
done
case "$FIXTURE_PORT" in *[!0-9]*|'') fail "FIXTURE_PORT must be numeric" ;; esac
[ "$FIXTURE_PORT" -ge 1024 ] && [ "$FIXTURE_PORT" -le 65535 ] || fail "FIXTURE_PORT is out of range"

RUN_ROOT=$(/usr/bin/mktemp -d "$RUN_PARENT/codex-lb-http-contract.XXXXXXXX") || fail "create run root"
[ "$(/usr/bin/stat -f '%Lp' "$RUN_ROOT")" = 700 ] || fail "run root mode"
[ "$(/usr/bin/stat -f '%u' "$RUN_ROOT")" = "$(id -u)" ] || fail "run root owner"
/bin/mkdir -p "$RUN_ROOT"/{home,tmp,build,evidence,auth,data} || fail "create run directories"
export HOME="$RUN_ROOT/home"
export TMPDIR="$RUN_ROOT/tmp"
export XDG_CONFIG_HOME="$HOME/.config"
export XDG_CACHE_HOME="$HOME/.cache"
/bin/mkdir -p "$XDG_CONFIG_HOME" "$XDG_CACHE_HOME" || fail "create private config directories"

for path in "$CLIPROXY_SOURCE" "$CLIPROXY_GIT" "$GO_MODCACHE" "$CODEX_LB_REPO" "$PYTHON_SITE_PACKAGES" "$RUN_PARENT"; do
  [ -d "$path" ] || fail "required directory missing: $path"
  [ "$(/bin/realpath "$path")" = "$path" ] || fail "directory is not physical: $path"
done
[ -x "$GO_BIN" ] && [ "$(/bin/realpath "$GO_BIN")" = "$GO_BIN" ] || fail "Go executable must be physical"
[ -x "$TIMEOUT_BIN" ] && [ "$(/bin/realpath "$TIMEOUT_BIN")" = "$TIMEOUT_BIN" ] || fail "timeout executable must be physical"
[ -x "$PYTHON_VENV" ] || fail "venv Python invocation missing"
[ "$(/bin/realpath "$PYTHON_VENV")" = "$PYTHON_TARGET" ] || fail "venv Python target mismatch"
[ -f "$PYVENV_CFG" ] && [ "$(/bin/realpath "$PYVENV_CFG")" = "$PYVENV_CFG" ] || fail "pyvenv.cfg mismatch"
case "$PYTHON_VENV" in "$CODEX_LB_REPO"/.venv/bin/python) : ;; *) fail "unexpected venv invocation" ;; esac
case "$PYVENV_CFG" in "$CODEX_LB_REPO"/.venv/pyvenv.cfg) : ;; *) fail "unexpected pyvenv.cfg" ;; esac
case "$PYTHON_SITE_PACKAGES" in "$CODEX_LB_REPO"/.venv/lib/python*/site-packages) : ;; *) fail "unexpected venv site-packages directory" ;; esac
case "$EDITABLE_PTH" in "$PYTHON_SITE_PACKAGES"/_editable_impl_codex_lb.pth) : ;; *) fail "unexpected editable pth" ;; esac

VIRTUALENV_PTH="$PYTHON_SITE_PACKAGES/_virtualenv.pth"
COVERAGE_PTH="$PYTHON_SITE_PACKAGES/a1_coverage.pth"
for file in "$VIRTUALENV_PTH" "$COVERAGE_PTH" "$EDITABLE_PTH"; do [ -f "$file" ] || fail "startup input missing: $file"; done
[ "$(/bin/cat "$EDITABLE_PTH")" = "$CODEX_LB_REPO" ] || fail "editable pth does not bind this source root exactly"
extra_pth=$(/usr/bin/find "$PYTHON_SITE_PACKAGES" -maxdepth 1 -name '*.pth' ! -name '_virtualenv.pth' ! -name 'a1_coverage.pth' ! -name '_editable_impl_codex_lb.pth' -print)
[ -z "$extra_pth" ] || fail "unreviewed Python startup hook: $extra_pth"

export GIT_OPTIONAL_LOCKS=0 GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_SYSTEM=/dev/null GIT_TERMINAL_PROMPT=0
git_ro() { /usr/bin/git -C "$CLIPROXY_SOURCE" -c core.fsmonitor=false -c core.untrackedCache=false -c core.hooksPath=/dev/null -c gc.auto=0 -c maintenance.auto=false "$@"; }
actual_git=$(git_ro rev-parse --path-format=absolute --git-common-dir); GIT_DIR_RC=$?
echo "GIT_COMMON_DIR_EXIT=$GIT_DIR_RC" > "$RUN_ROOT/evidence/exits.txt"
[ "$GIT_DIR_RC" -eq 0 ] || fail "read Git common directory"
[ "$(/bin/realpath "$actual_git")" = "$CLIPROXY_GIT" ] || fail "Git common directory mismatch"
actual_commit=$(git_ro rev-parse HEAD); GIT_HEAD_RC=$?
echo "GIT_HEAD_EXIT=$GIT_HEAD_RC" >> "$RUN_ROOT/evidence/exits.txt"
[ "$GIT_HEAD_RC" -eq 0 ] && [ "$actual_commit" = "$PINNED_COMMIT" ] || fail "CLIProxyAPI revision mismatch"
dirty=$(git_ro status --porcelain --untracked-files=all); GIT_STATUS_RC=$?
echo "GIT_STATUS_EXIT=$GIT_STATUS_RC" >> "$RUN_ROOT/evidence/exits.txt"
[ "$GIT_STATUS_RC" -eq 0 ] || fail "read CLIProxyAPI status"
[ -z "$dirty" ] || fail "CLIProxyAPI checkout is dirty"

HTTP_TEST_DIR="$CODEX_LB_REPO/tests/contract/cliproxy_exclusions/http"
GO_BACKING="$HTTP_TEST_DIR/management_fixture_test.go"; PY_BACKING="$HTTP_TEST_DIR/test_http_roundtrip.py"; PYTEST_CONFIG="$HTTP_TEST_DIR/pytest.ini"
[ "$(/usr/bin/shasum -a 256 "$GO_BACKING" | /usr/bin/awk '{print $1}')" = "$GO_BACKING_SHA" ] || fail "Go backing hash mismatch"
[ "$(/usr/bin/shasum -a 256 "$PY_BACKING" | /usr/bin/awk '{print $1}')" = "$PY_BACKING_SHA" ] || fail "Python backing hash mismatch"
[ "$(/usr/bin/shasum -a 256 "$PYTEST_CONFIG" | /usr/bin/awk '{print $1}')" = "$PYTEST_CONFIG_SHA" ] || fail "pytest config hash mismatch"

TARGET="$CLIPROXY_SOURCE/internal/api/handlers/management/codex_lb_http_fixture_test.go"
[ ! -e "$TARGET" ] && [ ! -L "$TARGET" ] || fail "overlay target exists"
for path in "$GO_BACKING" "$TARGET"; do case "$path" in *\"*|*\\*|*$'\n'*|*$'\r'*|*$'\t'*) fail "overlay path has unsupported JSON characters" ;; esac; done
OVERLAY="$RUN_ROOT/overlay.json"
/usr/bin/printf '{\n  "Replace": {\n    "%s": "%s"\n  }\n}\n' "$TARGET" "$GO_BACKING" > "$OVERLAY" || fail "write overlay"
/usr/bin/printf '%s\n' '{"type":"claude","email":"alpha@synthetic.invalid","access_token":"synthetic-token-alpha","refresh_token":"synthetic-refresh-alpha","expired":"2099-01-01T00:00:00Z"}' > "$RUN_ROOT/auth/alpha.json"
/usr/bin/printf '%s\n' '{"type":"claude","email":"bravo@synthetic.invalid","access_token":"synthetic-token-bravo","refresh_token":"synthetic-refresh-bravo","expired":"2099-01-01T00:00:00Z"}' > "$RUN_ROOT/auth/bravo.json"

GO_ENV=(/usr/bin/env -i PATH=/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin HOME="$HOME" TMPDIR="$TMPDIR" GOPATH="$HOME/go" GOCACHE="$RUN_ROOT/build" GOMODCACHE="$GO_MODCACHE" GOFLAGS=-mod=readonly GOPROXY=off GOSUMDB=off GONOSUMDB='*' GOTOOLCHAIN=local GOENV=off GOWORK=off GOOS=darwin GOARCH=arm64)
"${GO_ENV[@]}" "$GO_BIN" telemetry off > "$RUN_ROOT/evidence/go-telemetry-set.log" 2>&1 || fail "disable Go telemetry"
"${GO_ENV[@]}" "$GO_BIN" env GOTELEMETRY GOTELEMETRYDIR > "$RUN_ROOT/evidence/go-env.log" 2>&1 || fail "read Go telemetry"
[ "$(/usr/bin/head -n 1 "$RUN_ROOT/evidence/go-env.log")" = off ] || fail "Go telemetry is not off"
telemetry_dir=$(/usr/bin/tail -n 1 "$RUN_ROOT/evidence/go-env.log")
case "$telemetry_dir" in "$HOME"/*) : ;; *) fail "Go telemetry directory is outside private HOME" ;; esac

TEST_BINARY="$RUN_ROOT/management-fixture.test"
trap on_exit EXIT
trap on_interrupt INT
trap on_terminate TERM
(
  # The nested shell expands its positional arguments.
  # shellcheck disable=SC2016
  exec "$TIMEOUT_BIN" --signal=TERM --kill-after=5s 120s /bin/bash --noprofile --norc -c 'cd "$1" && exec "${@:2}"' _ "$CLIPROXY_SOURCE" "${GO_ENV[@]}" "$GO_BIN" test -overlay "$OVERLAY" -c -o "$TEST_BINARY" github.com/router-for-me/CLIProxyAPI/v7/internal/api/handlers/management
) > "$RUN_ROOT/evidence/go-compile.log" 2>&1 &
COMPILE_STAGE_PID=$!
wait_owned "$COMPILE_STAGE_PID"; COMPILE_RC=$?
COMPILE_REAPED=1
echo "GO_COMPILE_EXIT=$COMPILE_RC" >> "$RUN_ROOT/evidence/exits.txt"
if group_exists "$COMPILE_STAGE_PID"; then
  stop_group compile "$COMPILE_STAGE_PID" || fail "compile process group did not stop"
else
  echo "GROUP_EMPTY=compile:$COMPILE_STAGE_PID" >> "$RUN_ROOT/evidence/exits.txt"
fi
[ "$COMPILE_RC" -eq 0 ] && [ -x "$TEST_BINARY" ] || fail "Go fixture compilation failed or timed out"

READY="$RUN_ROOT/ready"; STOP="$RUN_ROOT/stop"
FIXTURE_ENV=(/usr/bin/env -i PATH=/usr/bin:/bin:/usr/sbin:/sbin HOME="$HOME" TMPDIR="$TMPDIR" CODEX_LB_HTTP_FIXTURE=1 CODEX_LB_HTTP_FIXTURE_ADDR="127.0.0.1:$FIXTURE_PORT" CODEX_LB_HTTP_FIXTURE_AUTH_DIR="$RUN_ROOT/auth" CODEX_LB_HTTP_FIXTURE_READY="$READY" CODEX_LB_HTTP_FIXTURE_STOP="$STOP")
(
  exec "$TIMEOUT_BIN" --signal=TERM --kill-after=5s 80s "${FIXTURE_ENV[@]}" "$TEST_BINARY" -test.v -test.run '^TestCodexLBManagementHTTPFixture$' -test.timeout 75s
) > "$RUN_ROOT/evidence/go-fixture.log" 2>&1 &
GO_STAGE_PID=$!
ready_deadline=200
while [ ! -f "$READY" ]; do
  /bin/kill -0 "$GO_STAGE_PID" 2>/dev/null || fail "Go fixture exited before ready"
  ready_deadline=$((ready_deadline - 1)); [ "$ready_deadline" -gt 0 ] || fail "listener readiness timeout"
  /bin/sleep 0.025
done
[ "$(/bin/cat "$READY")" = "127.0.0.1:$FIXTURE_PORT" ] || fail "unexpected listener address"

PY_ENV=(/usr/bin/env -i PATH=/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin HOME="$HOME" TMPDIR="$TMPDIR" XDG_CONFIG_HOME="$XDG_CONFIG_HOME" XDG_CACHE_HOME="$XDG_CACHE_HOME" PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPYCACHEPREFIX="$RUN_ROOT/tmp/pycache" PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 COVERAGE_PROCESS_START= COVERAGE_PROCESS_CONFIG= CODEX_LB_DATABASE_URL="sqlite+aiosqlite:///$RUN_ROOT/codex-lb.db" CODEX_LB_DATA_DIR="$RUN_ROOT/data" CODEX_LB_UPSTREAM_BASE_URL=https://example.invalid/backend-api CODEX_LB_AUTH_GUARDIAN_ENABLED=false CODEX_LB_USAGE_REFRESH_ENABLED=false CODEX_LB_LIVE_USAGE_INGESTION_ENABLED=false CODEX_LB_RATE_LIMIT_RESET_CREDITS_REFRESH_ENABLED=false CODEX_LB_MODEL_REGISTRY_ENABLED=false CODEX_LB_STICKY_SESSION_CLEANUP_ENABLED=false CODEX_LB_HTTP_RESPONSES_SESSION_BRIDGE_ENABLED=false CODEX_LB_QUOTA_PLANNER_SCHEDULER_ENABLED=false CODEX_LB_AUTOMATIONS_SCHEDULER_ENABLED=false CODEX_LB_LEADER_ELECTION_ENABLED=false CODEX_LB_TELEMETRY_ENABLED=false CODEX_LB_IMAGE_INLINE_FETCH_ENABLED=false CODEX_LB_OTEL_ENABLED=false CODEX_LB_ENCRYPTION_KEY_FILE="$RUN_ROOT/encryption.key" CODEX_LB_HTTP_FIXTURE_BASE_URL="http://127.0.0.1:$FIXTURE_PORT" CODEX_LB_HTTP_FIXTURE_AUTH_DIR="$RUN_ROOT/auth")
(
  # The nested shell expands its positional arguments.
  # shellcheck disable=SC2016
  exec "$TIMEOUT_BIN" --signal=TERM --kill-after=5s 60s /bin/bash --noprofile --norc -c 'cd "$1" && exec "${@:2}"' _ "$CODEX_LB_REPO" "${PY_ENV[@]}" "$PYTHON_VENV" -m pytest -c "$PYTEST_CONFIG" -p pytest_asyncio.plugin --confcutdir="$HTTP_TEST_DIR" --rootdir="$HTTP_TEST_DIR" -q "$PY_BACKING"
) > "$RUN_ROOT/evidence/python.log" 2>&1 &
PY_STAGE_PID=$!
wait_owned "$PY_STAGE_PID"; PY_RC=$?
PY_REAPED=1
echo "PYTHON_EXIT=$PY_RC" >> "$RUN_ROOT/evidence/exits.txt"
if group_exists "$PY_STAGE_PID"; then
  stop_group python "$PY_STAGE_PID" || fail "Python process group did not stop"
else
  echo "GROUP_EMPTY=python:$PY_STAGE_PID" >> "$RUN_ROOT/evidence/exits.txt"
fi
/usr/bin/touch "$STOP" || fail "signal fixture stop"
wait_owned "$GO_STAGE_PID"; GO_RC=$?
GO_REAPED=1
echo "GO_FIXTURE_EXIT=$GO_RC" >> "$RUN_ROOT/evidence/exits.txt"
if group_exists "$GO_STAGE_PID"; then
  stop_group fixture "$GO_STAGE_PID" || fail "fixture process group did not stop"
else
  echo "GROUP_EMPTY=fixture:$GO_STAGE_PID" >> "$RUN_ROOT/evidence/exits.txt"
fi

/usr/bin/grep -q '^=== RUN   TestCodexLBManagementHTTPFixture$' "$RUN_ROOT/evidence/go-fixture.log" || fail "missing Go RUN"
/usr/bin/grep -q '^--- PASS: TestCodexLBManagementHTTPFixture ' "$RUN_ROOT/evidence/go-fixture.log" || fail "missing Go PASS"
/usr/bin/grep -q '^1 passed' "$RUN_ROOT/evidence/python.log" || fail "missing Python pass count"
trap - EXIT INT TERM
echo "CLEANUP_CONFIRMED=1" >> "$RUN_ROOT/evidence/exits.txt"
echo "RUN_ROOT=$RUN_ROOT"
/bin/cat "$RUN_ROOT/evidence/exits.txt"
[ "$PY_RC" -eq 0 ] && [ "$GO_RC" -eq 0 ] || exit 1
