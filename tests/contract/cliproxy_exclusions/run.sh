#!/bin/bash
# Child entry for the opt-in macOS CLIProxyAPI exclusion contracts.
# Do not invoke directly. Use the complete sandbox-exec command documented in
# README.md. An environment marker records intended launch shape only and does
# not prove sandbox enforcement.

set -u
set -o pipefail
umask 077

PINNED_COMMIT=856ddd8df746a38a6033dbbf6c140974bf5aea0f
TEST_SELECTOR='^(TestExclusionContract_ExactIDSkipsOnlyThatWireID|TestExclusionContract_ExplicitWildcardSkipsEveryMatch|TestExclusionContract_ExcludedAccountReceivesNoCallOnSelectionOrRetry|TestExclusionContract_AnotherEligibleAccountServes|TestExclusionContract_NoEligibleAccountPreservesExhaustion|TestExclusionContract_ToggleChangesEligibilityWithoutRestart|TestExclusionContract_AliasDoesNotReviveExcludedWireID|TestExclusionWatcher_SavedAddAndClearReachSelection)$'
GO_TEST_TIMEOUT=120s
EXPECTED_TESTS=(
  TestExclusionContract_ExactIDSkipsOnlyThatWireID
  TestExclusionContract_ExplicitWildcardSkipsEveryMatch
  TestExclusionContract_ExcludedAccountReceivesNoCallOnSelectionOrRetry
  TestExclusionContract_AnotherEligibleAccountServes
  TestExclusionContract_NoEligibleAccountPreservesExhaustion
  TestExclusionContract_ToggleChangesEligibilityWithoutRestart
  TestExclusionContract_AliasDoesNotReviveExcludedWireID
  TestExclusionWatcher_SavedAddAndClearReachSelection
)

fail() { echo "PREFLIGHT_FAIL: $*" >&2; exit 91; }

require_absolute_dir() {
  local label="$1" path="$2"
  case "$path" in /*) : ;; *) fail "$label must be absolute: $path" ;; esac
  [ -d "$path" ] || fail "$label is not an existing directory: $path"
  [ -L "$path" ] && fail "$label must already be symlink-resolved: $path"
  local resolved
  resolved=$(/bin/realpath "$path") || fail "realpath $label"
  [ "$resolved" = "$path" ] || fail "$label must be physical: got $path, want $resolved"
}

require_absolute_file() {
  local label="$1" path="$2"
  case "$path" in /*) : ;; *) fail "$label must be absolute: $path" ;; esac
  [ -f "$path" ] || fail "$label is not an existing file: $path"
  [ -L "$path" ] && fail "$label must already be symlink-resolved: $path"
  local resolved
  resolved=$(/bin/realpath "$path") || fail "realpath $label"
  [ "$resolved" = "$path" ] || fail "$label must be physical: got $path, want $resolved"
}

# These inputs must be supplied identically to sandbox-exec -D parameters in the
# documented parent command. The checks below verify their physical identities
# and relationships, but cannot prove that the parent sandbox is enforcing them.
[ "${CODEX_LB_CONTRACT_LAUNCH:-}" = "1" ] || fail "use the documented sandbox-exec invocation"
[ -n "${CLIPROXY_SOURCE:-}" ] || fail "CLIPROXY_SOURCE is required"
[ -n "${CLIPROXY_GIT:-}" ] || fail "CLIPROXY_GIT is required"
[ -n "${GO_MODCACHE:-}" ] || fail "GO_MODCACHE is required"
[ -n "${CODEX_LB_REPO:-}" ] || fail "CODEX_LB_REPO is required"
[ -n "${GO_BIN:-}" ] || fail "GO_BIN is required"
[ -n "${RUN_PARENT:-}" ] || fail "RUN_PARENT is required"
[ -z "${BASH_ENV:-}" ] || fail "BASH_ENV leaked into sanitized shell"
[ -z "${ENV:-}" ] || fail "ENV leaked into sanitized shell"
[ -z "${GOFLAGS:-}" ] || fail "ambient GOFLAGS leaked into sanitized shell"
[ "$(id -u)" != "0" ] || fail "refusing to run as root"

require_absolute_dir "run parent" "$RUN_PARENT"
RUN_ROOT=$(/usr/bin/mktemp -d "$RUN_PARENT/codex-lb-cliproxy-contract.XXXXXXXX") || fail "create fresh run root"
[ -d "$RUN_ROOT" ] || fail "fresh run root missing"
[ -L "$RUN_ROOT" ] && fail "fresh run root is a symlink"
[ "$(/usr/bin/stat -f '%Lp' "$RUN_ROOT")" = "700" ] || fail "fresh run root is not mode 700"
[ "$(/usr/bin/stat -f '%u' "$RUN_ROOT")" = "$(id -u)" ] || fail "fresh run root owner mismatch"
/bin/mkdir -p "$RUN_ROOT"/{home,tmp,build,out} || fail "create synthetic writable directories"

# Establish private writable locations before any Git or Go preflight.
export HOME="$RUN_ROOT/home"
export TMPDIR="$RUN_ROOT/tmp"
export XDG_CONFIG_HOME="$HOME/.config"
export XDG_CACHE_HOME="$HOME/.cache"
/bin/mkdir -p "$XDG_CONFIG_HOME" "$XDG_CACHE_HOME" || fail "create synthetic config directories"

require_absolute_dir "CLIProxyAPI source" "$CLIPROXY_SOURCE"
require_absolute_dir "Git common directory" "$CLIPROXY_GIT"
require_absolute_dir "Go module cache" "$GO_MODCACHE"
require_absolute_dir "codex-lb repository" "$CODEX_LB_REPO"
require_absolute_file "Go executable" "$GO_BIN"
[ -x "$GO_BIN" ] || fail "Go executable is not executable: $GO_BIN"

TEST_DIR="$CODEX_LB_REPO/tests/contract/cliproxy_exclusions"
POLICY="$TEST_DIR/sandbox.sb"
ACCOUNT_TEST="$TEST_DIR/account_selection_test.go"
WATCHER_TEST="$TEST_DIR/watcher_selection_test.go"
require_absolute_file "sandbox policy" "$POLICY"
require_absolute_file "account-selection backing" "$ACCOUNT_TEST"
require_absolute_file "watcher-selection backing" "$WATCHER_TEST"

export GIT_OPTIONAL_LOCKS=0
export GIT_CONFIG_NOSYSTEM=1
export GIT_CONFIG_GLOBAL=/dev/null
export GIT_CONFIG_SYSTEM=/dev/null
export GIT_TERMINAL_PROMPT=0

git_ro() {
  /usr/bin/git -C "$CLIPROXY_SOURCE" \
    -c core.fsmonitor=false -c core.untrackedCache=false \
    -c core.hooksPath=/dev/null -c gc.auto=0 -c maintenance.auto=false "$@"
}

actual_git=$(git_ro rev-parse --path-format=absolute --git-common-dir) || fail "read Git common directory"
actual_git=$(/bin/realpath "$actual_git") || fail "realpath observed Git common directory"
[ "$actual_git" = "$CLIPROXY_GIT" ] || fail "Git common directory differs from policy/child input"
actual_commit=$(git_ro rev-parse HEAD) || fail "read CLIProxyAPI revision"
[ "$actual_commit" = "$PINNED_COMMIT" ] || fail "CLIProxyAPI revision $actual_commit != $PINNED_COMMIT"
dirty=$(git_ro status --porcelain --untracked-files=all) || fail "read CLIProxyAPI status"
[ -z "$dirty" ] || fail "CLIProxyAPI checkout is not clean"

TARGET_ACCOUNT="$CLIPROXY_SOURCE/sdk/cliproxy/codex_lb_account_selection_contract_test.go"
TARGET_WATCHER="$CLIPROXY_SOURCE/sdk/cliproxy/codex_lb_watcher_selection_contract_test.go"
for target in "$TARGET_ACCOUNT" "$TARGET_WATCHER"; do
  case "$target" in *_test.go) : ;; *) fail "overlay target is not a Go test: $target" ;; esac
  [ ! -e "$target" ] || fail "overlay target already exists: $target"
  [ ! -L "$target" ] || fail "overlay target is a symlink: $target"
done

# JSON string escaping is intentionally bounded. Reject characters that require
# escaping rather than producing an invalid overlay map.
for path in "$TARGET_ACCOUNT" "$TARGET_WATCHER" "$ACCOUNT_TEST" "$WATCHER_TEST"; do
  case "$path" in
    *\"*|*\\*|*$'\n'*|*$'\r'*|*$'\t'*) fail "overlay paths cannot contain quotes, backslashes or control whitespace: $path" ;;
  esac
done

OVERLAY_JSON="$RUN_ROOT/overlay.json"
/usr/bin/printf '{\n  "Replace": {\n    "%s": "%s",\n    "%s": "%s"\n  }\n}\n' \
  "$TARGET_ACCOUNT" "$ACCOUNT_TEST" "$TARGET_WATCHER" "$WATCHER_TEST" > "$OVERLAY_JSON" \
  || fail "write overlay map"

GO_ENV=(
  /usr/bin/env -i
  PATH=/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin
  HOME="$HOME"
  TMPDIR="$TMPDIR"
  GOPATH="$HOME/go"
  GOCACHE="$RUN_ROOT/build"
  GOMODCACHE="$GO_MODCACHE"
  GOFLAGS=-mod=readonly
  GOPROXY=off
  GOSUMDB=off
  GONOSUMDB='*'
  GOTOOLCHAIN=local
  GOENV=off
  GOWORK=off
  GOOS=darwin
  GOARCH=arm64
)

"${GO_ENV[@]}" "$GO_BIN" telemetry off || fail "disable Go telemetry in synthetic HOME"
"${GO_ENV[@]}" "$GO_BIN" env GOTELEMETRY GOTELEMETRYDIR > "$RUN_ROOT/out/go-env.txt" 2>&1 \
  || fail "read back synthetic telemetry configuration"

LOG="$RUN_ROOT/out/go-test.log"
cd "$CLIPROXY_SOURCE" || fail "enter CLIProxyAPI checkout"
"${GO_ENV[@]}" "$GO_BIN" test \
  -overlay "$OVERLAY_JSON" \
  -count=1 \
  -timeout "$GO_TEST_TIMEOUT" \
  -run "$TEST_SELECTOR" \
  -v \
  github.com/router-for-me/CLIProxyAPI/v7/sdk/cliproxy \
  > "$LOG" 2>&1
rc=$?

echo "RUN_ROOT=$RUN_ROOT"
echo "GO_TEST_EXIT=$rc"
echo "LOG=$LOG"

verdict=0
if [ "$rc" -ne 0 ]; then
  echo "RESULT: go test exit $rc"
  verdict=1
fi
if /usr/bin/grep -q '^testing: warning: no tests to run' "$LOG"; then
  echo "RESULT: go reported no tests to run"
  verdict=1
fi
for name in "${EXPECTED_TESTS[@]}"; do
  if ! /usr/bin/grep -q "^=== RUN   ${name}\$" "$LOG"; then
    echo "RESULT: missing RUN for $name"
    verdict=1
    continue
  fi
  if ! /usr/bin/grep -q "^--- PASS: ${name} " "$LOG"; then
    echo "RESULT: missing PASS for $name"
    verdict=1
  fi
done
if /usr/bin/grep -q '^--- FAIL' "$LOG"; then
  echo "RESULT: a FAIL marker is present"
  verdict=1
fi

if [ "$verdict" -eq 0 ]; then
  echo "RESULT: all ${#EXPECTED_TESTS[@]} selected tests ran and passed"
else
  echo "RESULT: NOT accepted"
fi
exit "$verdict"
