from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_DEPLOY_SCRIPT = _REPOSITORY_ROOT / "scripts" / "deploy-codex-lb.sh"

_GIT_IDENTITY = (
    "-c",
    "user.email=deploy-test@example.com",
    "-c",
    "user.name=deploy-test",
)


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _commit_all(repo: Path, message: str, filename: str = "app.txt", content: str | None = None) -> str:
    (repo / filename).write_text(content if content is not None else message, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, *_GIT_IDENTITY, "commit", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _push_seed_to_origin(seed: Path) -> None:
    _git(seed, "push", "--quiet", "origin", "main")


def _stub_bin(tmp_path: Path) -> Path:
    """Stub commands the deploy script requires but the test must not run."""
    bin_dir = tmp_path / "stub-bin"
    bin_dir.mkdir()
    for name in ("systemctl", "curl", "uv"):
        stub = bin_dir / name
        stub.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
        stub.chmod(0o755)
    return bin_dir


def _make_deploy_fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Bare origin + seed checkout (for pushing to origin) + deploy clone."""
    origin = tmp_path / "origin.git"
    subprocess.run(
        ["git", "init", "--bare", "-b", "main", str(origin)],
        check=True,
        capture_output=True,
    )
    seed = tmp_path / "seed"
    subprocess.run(
        ["git", "clone", "--quiet", str(origin), str(seed)],
        check=True,
        capture_output=True,
    )
    _git(seed, "config", "user.email", "deploy-test@example.com")
    _git(seed, "config", "user.name", "deploy-test")
    _commit_all(seed, "seed commit")
    _push_seed_to_origin(seed)
    deploy = tmp_path / "deploy"
    subprocess.run(
        ["git", "clone", "--quiet", str(origin), str(deploy)],
        check=True,
        capture_output=True,
    )
    _git(deploy, "config", "user.email", "deploy-test@example.com")
    _git(deploy, "config", "user.name", "deploy-test")
    return origin, seed, deploy


def _run_deploy(
    tmp_path: Path,
    deploy: Path,
    bin_dir: Path,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update(
        {
            "CODEX_LB_DEPLOY_DIR": str(deploy),
            "CODEX_LB_DEPLOY_LOG_DIR": str(tmp_path / "deploy-logs"),
            "CODEX_LB_DEPLOY_LOCK": str(tmp_path / "deploy-logs" / "deploy.lock"),
            "CODEX_LB_DEPLOY_LAUNCHER": str(tmp_path / "launcher" / "deploy-codex-lb.sh"),
            "CODEX_LB_SKIP_RESTART": "1",
            "CODEX_LB_SKIP_FRONTEND": "1",
            "UV_BIN": str(bin_dir / "uv"),
            "PATH": f"{bin_dir}{os.pathsep}{env['PATH']}",
        }
    )
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        ["bash", str(_DEPLOY_SCRIPT)],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )


def _read_latest_log(tmp_path: Path) -> str:
    return (tmp_path / "deploy-logs" / "latest.log").read_text(encoding="utf-8")


def _backup_branches(deploy: Path) -> dict[str, str]:
    out = _git(deploy, "for-each-ref", "--format=%(refname:short) %(objectname)", "refs/heads/backup/")
    return dict(line.split() for line in out.splitlines() if line)


def _assert_deployed_to_origin_main(deploy: Path) -> None:
    assert _git(deploy, "rev-parse", "HEAD") == _git(deploy, "rev-parse", "origin/main")
    assert _git(deploy, "status", "--porcelain") == ""


def test_fast_forward_deploy_is_untouched(tmp_path: Path) -> None:
    origin, seed, deploy = _make_deploy_fixture(tmp_path)
    bin_dir = _stub_bin(tmp_path)
    _commit_all(seed, "new commit on origin")
    _push_seed_to_origin(seed)

    result = _run_deploy(tmp_path, deploy, bin_dir)

    assert result.returncode == 0, result.stdout + result.stderr
    _assert_deployed_to_origin_main(deploy)
    assert _backup_branches(deploy) == {}
    assert _git(deploy, "stash", "list") == ""
    assert "fast-forward" in _read_latest_log(tmp_path)


def test_diverged_local_commits_are_preserved_on_backup_branch(tmp_path: Path) -> None:
    origin, seed, deploy = _make_deploy_fixture(tmp_path)
    bin_dir = _stub_bin(tmp_path)
    local_sha = _commit_all(deploy, "local-only commit", "local.txt", "local")
    _commit_all(seed, "remote commit")
    _push_seed_to_origin(seed)

    result = _run_deploy(tmp_path, deploy, bin_dir)

    assert result.returncode == 0, result.stdout + result.stderr
    _assert_deployed_to_origin_main(deploy)
    backups = _backup_branches(deploy)
    assert len(backups) == 1
    [(branch_name, branch_sha)] = backups.items()
    assert branch_name.startswith("backup/deploy-preserved-")
    assert branch_sha == local_sha
    # The preserved commit must stay reachable and its content intact.
    assert (deploy.parent / "deploy" / "local.txt").exists() is False
    assert _git(deploy, "stash", "list") == ""
    log = _read_latest_log(tmp_path)
    assert "PRESERVED local commits" in log
    assert local_sha in log
    assert "local-only commit" in log


def test_ahead_local_commits_are_preserved_on_backup_branch(tmp_path: Path) -> None:
    origin, seed, deploy = _make_deploy_fixture(tmp_path)
    bin_dir = _stub_bin(tmp_path)
    local_sha = _commit_all(deploy, "local-only commit", "local.txt", "local")

    result = _run_deploy(tmp_path, deploy, bin_dir)

    assert result.returncode == 0, result.stdout + result.stderr
    _assert_deployed_to_origin_main(deploy)
    backups = _backup_branches(deploy)
    assert len(backups) == 1
    [(branch_name, branch_sha)] = backups.items()
    assert branch_name.startswith("backup/deploy-preserved-")
    assert branch_sha == local_sha
    assert "PRESERVED local commits" in _read_latest_log(tmp_path)


def test_dirty_tree_is_stashed_and_never_discarded(tmp_path: Path) -> None:
    origin, seed, deploy = _make_deploy_fixture(tmp_path)
    bin_dir = _stub_bin(tmp_path)
    (deploy / "app.txt").write_text("tracked modification", encoding="utf-8")
    (deploy / "notes.txt").write_text("untracked WIP", encoding="utf-8")

    result = _run_deploy(tmp_path, deploy, bin_dir)

    assert result.returncode == 0, result.stdout + result.stderr
    _assert_deployed_to_origin_main(deploy)
    stash_list = _git(deploy, "stash", "list")
    assert "deploy-preserved-" in stash_list
    # Untracked files are inside the stash's untracked commit (third parent).
    stash_untracked = _git(deploy, "ls-tree", "--name-only", "stash@{0}^3")
    assert "notes.txt" in stash_untracked
    # The tracked modification is in the stash too.
    assert "app.txt" in _git(deploy, "diff", "--name-only", "stash@{0}^", "stash@{0}")
    log = _read_latest_log(tmp_path)
    assert "PRESERVED dirty working tree" in log
    assert "deploy-preserved-" in log


def test_switch_branch_preserves_local_main_tip_not_the_pre_checkout_tip(tmp_path: Path) -> None:
    origin, seed, deploy = _make_deploy_fixture(tmp_path)
    bin_dir = _stub_bin(tmp_path)
    # Local main gets a commit that origin/main does not have.
    local_main_tip = _commit_all(deploy, "local commit on deploy main", "main-local.txt", "main-local")
    # Then the clone switches to a local feature branch with its own commit,
    # so the deploy must switch back to main (CODEX_LB_DEPLOY_SWITCH_BRANCH=1).
    _git(deploy, "checkout", "-b", "feature")
    feature_tip = _commit_all(deploy, "local commit on feature", "feature.txt", "feature")

    result = _run_deploy(tmp_path, deploy, bin_dir, extra_env={"CODEX_LB_DEPLOY_SWITCH_BRANCH": "1"})

    assert result.returncode == 0, result.stdout + result.stderr
    _assert_deployed_to_origin_main(deploy)
    backups = _backup_branches(deploy)
    assert len(backups) == 1
    [(branch_name, branch_sha)] = backups.items()
    assert branch_name.startswith("backup/deploy-preserved-")
    # The backup must point at the deployment branch tip (local main), not the
    # pre-checkout feature tip — otherwise the reset orphans main's commits.
    assert branch_sha == local_main_tip
    assert branch_sha != feature_tip
    # The feature branch and its commit stay reachable through the checkout.
    assert _git(deploy, "rev-parse", "--verify", "refs/heads/feature") == feature_tip
    log = _read_latest_log(tmp_path)
    assert "PRESERVED local commits" in log
    assert local_main_tip in log


def test_switch_branch_from_detached_head_preserves_pre_checkout_commits(tmp_path: Path) -> None:
    origin, seed, deploy = _make_deploy_fixture(tmp_path)
    bin_dir = _stub_bin(tmp_path)
    # Detach first so the commit is on no branch at all, then commit.
    _git(deploy, "checkout", "--quiet", "--detach", "origin/main")
    detached_tip = _commit_all(deploy, "local commit while detached", "detached.txt", "detached")

    result = _run_deploy(tmp_path, deploy, bin_dir, extra_env={"CODEX_LB_DEPLOY_SWITCH_BRANCH": "1"})

    assert result.returncode == 0, result.stdout + result.stderr
    _assert_deployed_to_origin_main(deploy)
    backups = _backup_branches(deploy)
    assert len(backups) == 1
    [(branch_name, branch_sha)] = backups.items()
    assert branch_name.startswith("backup/deploy-preserved-")
    assert branch_name.endswith("-pre")
    assert branch_sha == detached_tip
    assert "PRESERVED detached HEAD" in _read_latest_log(tmp_path)


def test_ignored_file_colliding_with_target_tree_is_preserved(tmp_path: Path) -> None:
    origin, seed, deploy = _make_deploy_fixture(tmp_path)
    bin_dir = _stub_bin(tmp_path)
    # A local ignored file that the remote starts tracking at the same path.
    (deploy / ".git" / "info" / "exclude").write_text("secrets.yaml\n", encoding="utf-8")
    (deploy / "secrets.yaml").write_text("LOCAL SECRET", encoding="utf-8")
    pusher = tmp_path / "pusher"
    subprocess.run(
        ["git", "clone", "--quiet", str(origin), str(pusher)],
        check=True,
        capture_output=True,
    )
    _git(pusher, "config", "user.email", "deploy-test@example.com")
    _git(pusher, "config", "user.name", "deploy-test")
    (pusher / "secrets.yaml").write_text("REMOTE TRACKED", encoding="utf-8")
    _git(pusher, "add", "-f", "secrets.yaml")
    _git(pusher, *_GIT_IDENTITY, "commit", "-m", "track secrets.yaml")
    _push_seed_to_origin(pusher)

    result = _run_deploy(tmp_path, deploy, bin_dir)

    assert result.returncode == 0, result.stdout + result.stderr
    _assert_deployed_to_origin_main(deploy)
    # The tracked content is checked out, but the local ignored file's
    # contents were moved aside first, not silently overwritten.
    assert (deploy / "secrets.yaml").read_text(encoding="utf-8") == "REMOTE TRACKED"
    preserved = list((tmp_path / "deploy-logs" / "ignored-preserved-").parent.glob("ignored-preserved-*/secrets.yaml"))
    assert len(preserved) == 1
    assert preserved[0].read_text(encoding="utf-8") == "LOCAL SECRET"
    log = _read_latest_log(tmp_path)
    assert "PRESERVED ignored file" in log
    assert "secrets.yaml" in log


def test_branch_mismatch_abort_leaves_ignored_files_untouched(tmp_path: Path) -> None:
    origin, seed, deploy = _make_deploy_fixture(tmp_path)
    bin_dir = _stub_bin(tmp_path)
    # The clone sits on a non-deploy branch with no SWITCH_BRANCH=1, and an
    # ignored file collides with the target tree.
    _git(deploy, "checkout", "-b", "feature")
    (deploy / ".git" / "info" / "exclude").write_text("secrets.yaml\n", encoding="utf-8")
    (deploy / "secrets.yaml").write_text("LOCAL SECRET", encoding="utf-8")
    pusher = tmp_path / "pusher"
    subprocess.run(
        ["git", "clone", "--quiet", str(origin), str(pusher)],
        check=True,
        capture_output=True,
    )
    _git(pusher, "config", "user.email", "deploy-test@example.com")
    _git(pusher, "config", "user.name", "deploy-test")
    (pusher / "secrets.yaml").write_text("REMOTE TRACKED", encoding="utf-8")
    _git(pusher, "add", "-f", "secrets.yaml")
    _git(pusher, *_GIT_IDENTITY, "commit", "-m", "track secrets.yaml")
    _push_seed_to_origin(pusher)

    result = _run_deploy(tmp_path, deploy, bin_dir)

    # The deploy must refuse on the branch mismatch WITHOUT mutating the
    # working tree first: the ignored file stays exactly where it was.
    assert result.returncode != 0
    assert (deploy / "secrets.yaml").read_text(encoding="utf-8") == "LOCAL SECRET"
    assert not list((tmp_path / "deploy-logs").glob("ignored-preserved-*"))
    log = _read_latest_log(tmp_path)
    assert "deploy dir is on 'feature', not 'main'" in log
    assert "PRESERVED ignored file" not in log


def test_ahead_with_allow_dirty_refuses_before_any_mutation(tmp_path: Path) -> None:
    origin, seed, deploy = _make_deploy_fixture(tmp_path)
    bin_dir = _stub_bin(tmp_path)
    local_sha = _commit_all(deploy, "local-only commit", "local.txt", "local")
    # An ignored file that the remote tree does not track: if any preservation
    # ran before the refusal, this file would be moved aside for nothing.
    (deploy / ".git" / "info" / "exclude").write_text("wip.yaml\n", encoding="utf-8")
    (deploy / "wip.yaml").write_text("LOCAL SECRET", encoding="utf-8")

    result = _run_deploy(tmp_path, deploy, bin_dir, extra_env={"CODEX_LB_DEPLOY_ALLOW_DIRTY": "1"})

    # ALLOW_DIRTY=1 cannot converge with a locally ahead branch: refuse
    # loudly BEFORE stashing, moving ignored files, or touching the tree.
    assert result.returncode != 0
    assert _git(deploy, "rev-parse", "HEAD") == local_sha
    assert (deploy / "wip.yaml").read_text(encoding="utf-8") == "LOCAL SECRET"
    assert not list((tmp_path / "deploy-logs").glob("ignored-preserved-*"))
    assert _backup_branches(deploy) == {}
    assert _git(deploy, "stash", "list") == ""
    log = _read_latest_log(tmp_path)
    assert "ERROR: local main is ahead of origin/main" in log
    assert "the deploy cannot converge" in log
    assert "=== codex-lb deploy failed ===" in log


def test_dirty_and_diverged_state_is_fully_preserved(tmp_path: Path) -> None:
    origin, seed, deploy = _make_deploy_fixture(tmp_path)
    bin_dir = _stub_bin(tmp_path)
    local_sha = _commit_all(deploy, "local-only commit", "local.txt", "local")
    (deploy / "app.txt").write_text("tracked modification", encoding="utf-8")
    (deploy / "notes.txt").write_text("untracked WIP", encoding="utf-8")
    _commit_all(seed, "remote commit")
    _push_seed_to_origin(seed)

    result = _run_deploy(tmp_path, deploy, bin_dir)

    assert result.returncode == 0, result.stdout + result.stderr
    _assert_deployed_to_origin_main(deploy)
    backups = _backup_branches(deploy)
    assert len(backups) == 1
    [(branch_name, branch_sha)] = backups.items()
    assert branch_name.startswith("backup/deploy-preserved-")
    assert branch_sha == local_sha
    assert "deploy-preserved-" in _git(deploy, "stash", "list")
    assert _git(deploy, "ls-tree", "--name-only", "stash@{0}^3") == "notes.txt"
    log = _read_latest_log(tmp_path)
    assert "PRESERVED local commits" in log
    assert "PRESERVED dirty working tree" in log


def test_deploy_waits_for_lock_and_deploys_the_queued_push(tmp_path: Path) -> None:
    origin, seed, deploy = _make_deploy_fixture(tmp_path)
    bin_dir = _stub_bin(tmp_path)
    lock_path = tmp_path / "deploy-logs" / "deploy.lock"
    lock_path.parent.mkdir(exist_ok=True)
    # A push merges to main while another (simulated) deploy holds the lock.
    _commit_all(seed, "push merged during a running deploy")
    _push_seed_to_origin(seed)
    holder = subprocess.Popen(["flock", str(lock_path), "sleep", "2"])
    try:
        time.sleep(0.5)
        result = _run_deploy(
            tmp_path,
            deploy,
            bin_dir,
            extra_env={"CODEX_LB_DEPLOY_LOCK_WAIT": "60"},
        )
    finally:
        holder.wait(timeout=30)

    assert result.returncode == 0, result.stdout + result.stderr
    _assert_deployed_to_origin_main(deploy)
    log = _read_latest_log(tmp_path)
    assert "waiting up to 60s" in log
    assert "waited" in log


def test_lock_wait_timeout_fails_loudly_and_nonzero(tmp_path: Path) -> None:
    origin, seed, deploy = _make_deploy_fixture(tmp_path)
    bin_dir = _stub_bin(tmp_path)
    lock_path = tmp_path / "deploy-logs" / "deploy.lock"
    lock_path.parent.mkdir(exist_ok=True)
    holder = subprocess.Popen(["flock", str(lock_path), "sleep", "3"])
    try:
        time.sleep(0.5)
        result = _run_deploy(
            tmp_path,
            deploy,
            bin_dir,
            extra_env={"CODEX_LB_DEPLOY_LOCK_WAIT": "1"},
        )
    finally:
        holder.kill()
        holder.wait(timeout=30)

    assert result.returncode != 0
    log = _read_latest_log(tmp_path)
    assert "ERROR: another deploy still held" in log
    assert "=== codex-lb deploy failed ===" in log


def test_allow_dirty_keeps_uncommitted_changes_and_fails_loudly_when_ahead(tmp_path: Path) -> None:
    origin, seed, deploy = _make_deploy_fixture(tmp_path)
    bin_dir = _stub_bin(tmp_path)
    _commit_all(deploy, "local-only commit", "local.txt", "local")
    (deploy / "app.txt").write_text("kept in place", encoding="utf-8")

    result = _run_deploy(tmp_path, deploy, bin_dir, extra_env={"CODEX_LB_DEPLOY_ALLOW_DIRTY": "1"})

    # ALLOW_DIRTY=1 keeps uncommitted changes in place; the deploy must then
    # refuse loudly instead of silently deploying nothing (HEAD stays ahead).
    assert result.returncode != 0
    assert _git(deploy, "rev-parse", "HEAD") != _git(deploy, "rev-parse", "origin/main")
    assert _git(deploy, "status", "--porcelain") != ""
    assert _backup_branches(deploy) == {}
    assert _git(deploy, "stash", "list") == ""
    log = _read_latest_log(tmp_path)
    assert "ERROR: local main is ahead of origin/main" in log
    assert "the deploy cannot converge" in log
    assert "=== codex-lb deploy failed ===" in log


# --- service layout (socket unit holds the port across restarts) -------------

_SYSTEMCTL_STUB = r"""#!/usr/bin/env bash
# Stateful systemctl stub: unit states live in $STUB_STATE/<unit>.state.
set -u
[[ "${1:-}" == "--user" ]] && shift
cmd=${1:-}
shift || true
printf '%s %s\n' "$cmd" "$*" >>"$STUB_STATE/calls.log"
state_of() { cat "$STUB_STATE/$1.state" 2>/dev/null || echo inactive; }
fail_for() { [[ -e "$STUB_STATE/fail-$cmd-$1" ]]; }
case "$cmd" in
  show-environment) echo "PATH=/usr/bin:/bin" ;;
  show)
    # Only `show -p ExecStart --value <unit>` is used: print the unit's argv.
    unit="${*: -1}"
    if [[ -e "$STUB_STATE/$unit.execstart" ]]; then
      printf '{ path=/x ; argv[]=%s ; ignore_errors=no ; start_time=[n/a] }\n' "$(cat "$STUB_STATE/$unit.execstart")"
    fi ;;
  is-active) s="$(state_of "$1")"; echo "$s"; [[ "$s" == active ]] ;;
  start | restart)
    for unit in "$@"; do
      if fail_for "$unit"; then echo failed >"$STUB_STATE/$unit.state"; exit 1; fi
      echo active >"$STUB_STATE/$unit.state"
    done ;;
  stop)
    for unit in "$@"; do echo inactive >"$STUB_STATE/$unit.state"; done ;;
  enable | disable | daemon-reload | reset-failed | status) ;;
  *) echo "unexpected systemctl $cmd" >&2; exit 2 ;;
esac
"""

# Ready only when the service is active, and not ready on the socket layout
# when the test asks for that failure.
_CURL_STUB = r"""#!/usr/bin/env bash
[[ "$(cat "$STUB_STATE/codex-lb.service.state" 2>/dev/null)" == active ]] || exit 7
if [[ -e "$STUB_STATE/not-ready-on-socket" && -e "$STUB_UNIT_DIR/codex-lb.service.d/50-socket-handoff.conf" ]]; then
  exit 22
fi
exit 0
"""


_PRODUCTION_EXEC_START = "/home/nohj/.local/bin/uv run codex-lb --host 0.0.0.0 --port 2455"


def _layout_env(
    tmp_path: Path,
    bin_dir: Path,
    *,
    entrypoint_ok: bool = True,
    exec_start: str | None = _PRODUCTION_EXEC_START,
) -> dict[str, str]:
    state = tmp_path / "systemd-state"
    state.mkdir(exist_ok=True)
    unit_dir = tmp_path / "units"
    (bin_dir / "systemctl").write_text(_SYSTEMCTL_STUB, encoding="utf-8")
    (bin_dir / "curl").write_text(_CURL_STUB, encoding="utf-8")
    (bin_dir / "journalctl").write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    for name in ("systemctl", "curl", "journalctl"):
        (bin_dir / name).chmod(0o755)
    venv_bin = tmp_path / "venv" / "bin"
    venv_bin.mkdir(parents=True, exist_ok=True)
    entrypoint = venv_bin / "codex-lb"
    entrypoint.write_text(f"#!/usr/bin/env bash\nexit {0 if entrypoint_ok else 1}\n", encoding="utf-8")
    entrypoint.chmod(0o755)
    # The service runs before the deploy, as a single unit.
    (state / "codex-lb.service.state").write_text("active\n", encoding="utf-8")
    if exec_start is not None:
        (state / "codex-lb.service.execstart").write_text(exec_start, encoding="utf-8")
    return {
        "CODEX_LB_SKIP_RESTART": "0",
        "CODEX_LB_SYSTEMD_USER_DIR": str(unit_dir),
        "CODEX_LB_VENV_DIR": str(tmp_path / "venv"),
        "CODEX_LB_HEALTH_RETRIES": "2",
        "CODEX_LB_HEALTH_SLEEP_SECS": "1",
        "CODEX_LB_ACTIVE_RETRIES": "2",
        "STUB_STATE": str(state),
        "STUB_UNIT_DIR": str(unit_dir),
    }


def _calls(tmp_path: Path) -> list[str]:
    path = tmp_path / "systemd-state" / "calls.log"
    if not path.exists():
        return []
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines()]


def _clear_calls(tmp_path: Path) -> None:
    (tmp_path / "systemd-state" / "calls.log").unlink(missing_ok=True)


def _state(tmp_path: Path, unit: str) -> str:
    path = tmp_path / "systemd-state" / f"{unit}.state"
    return path.read_text(encoding="utf-8").strip() if path.exists() else "inactive"


def _layout_record(tmp_path: Path) -> str:
    return (tmp_path / "deploy-logs" / "service-layout").read_text(encoding="utf-8").strip()


def _socket_file(tmp_path: Path) -> Path:
    return tmp_path / "units" / "codex-lb.socket"


def _dropin_file(tmp_path: Path) -> Path:
    return tmp_path / "units" / "codex-lb.service.d" / "50-socket-handoff.conf"


def _run_layout_command(tmp_path: Path, env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    full_env = os.environ.copy()
    full_env.update(
        {
            "CODEX_LB_DEPLOY_LOG_DIR": str(tmp_path / "deploy-logs"),
            "CODEX_LB_DEPLOY_LOCK": str(tmp_path / "deploy-logs" / "deploy.lock"),
            "PATH": f"{tmp_path / 'stub-bin'}{os.pathsep}{full_env['PATH']}",
            **env,
        }
    )
    return subprocess.run(
        ["bash", str(_DEPLOY_SCRIPT), *args],
        capture_output=True,
        text=True,
        env=full_env,
        timeout=120,
    )


def test_first_deploy_moves_the_service_to_the_socket_layout(tmp_path: Path) -> None:
    _origin, _seed, deploy = _make_deploy_fixture(tmp_path)
    bin_dir = _stub_bin(tmp_path)
    env = _layout_env(tmp_path, bin_dir)

    result = _run_deploy(tmp_path, deploy, bin_dir, extra_env=env)

    assert result.returncode == 0, result.stdout + result.stderr
    socket_unit = _socket_file(tmp_path).read_text(encoding="utf-8")
    assert "ListenStream=0.0.0.0:2455" in socket_unit
    assert "Service=codex-lb.service" in socket_unit
    dropin = _dropin_file(tmp_path).read_text(encoding="utf-8")
    venv = tmp_path / "venv"
    assert "Requires=codex-lb.socket" in dropin
    assert "ExecStart=\n" in dropin
    assert f"ExecStart={venv}/bin/codex-lb --host 0.0.0.0 --port 2455" in dropin
    assert f"Environment=PATH={venv}/bin:/usr/bin:/bin" in dropin
    assert "Environment=CODEX_LB_SHUTDOWN_DRAIN_TIMEOUT_SECONDS=120" in dropin
    assert "TimeoutStopSec=180" in dropin
    calls = _calls(tmp_path)
    # The running process owns the port, so it stops before the socket binds it.
    order = [calls.index(call) for call in ("stop codex-lb.service", "start codex-lb.socket", "start codex-lb.service")]
    assert order == sorted(order)
    assert "enable codex-lb.socket" in calls
    assert _state(tmp_path, "codex-lb.socket") == "active"
    assert _state(tmp_path, "codex-lb.service") == "active"
    assert _layout_record(tmp_path) == "socket"
    assert "health check OK (http://127.0.0.1:2455/health/ready)" in _read_latest_log(tmp_path)


@pytest.mark.parametrize(
    ("exec_start", "expected_listen"),
    [
        ("/usr/bin/uv run codex-lb --host 127.0.0.1 --port 2455", "127.0.0.1:2455"),
        ("/usr/bin/uv run codex-lb --host=127.0.0.1 --port=3000", "127.0.0.1:3000"),
        ("/usr/bin/uv run codex-lb --host localhost", "127.0.0.1:2455"),
        ("/usr/bin/uv run codex-lb --port 3000", "127.0.0.1:3000"),
        (None, "127.0.0.1:2455"),
    ],
)
def test_socket_keeps_the_address_the_service_binds_today(
    tmp_path: Path, exec_start: str | None, expected_listen: str
) -> None:
    _origin, _seed, deploy = _make_deploy_fixture(tmp_path)
    bin_dir = _stub_bin(tmp_path)
    env = _layout_env(tmp_path, bin_dir, exec_start=exec_start)

    result = _run_deploy(tmp_path, deploy, bin_dir, extra_env=env)

    assert result.returncode == 0, result.stdout + result.stderr
    assert f"ListenStream={expected_listen}\n" in _socket_file(tmp_path).read_text(encoding="utf-8")
    host, port = expected_listen.rsplit(":", 1)
    assert f"--host {host} --port {port}\n" in _dropin_file(tmp_path).read_text(encoding="utf-8")
    assert f"health check OK (http://127.0.0.1:{port}/health/ready)" in _read_latest_log(tmp_path)


def test_explicit_listen_override_wins(tmp_path: Path) -> None:
    _origin, _seed, deploy = _make_deploy_fixture(tmp_path)
    bin_dir = _stub_bin(tmp_path)
    env = {**_layout_env(tmp_path, bin_dir), "CODEX_LB_LISTEN": "127.0.0.1:2460"}

    result = _run_deploy(tmp_path, deploy, bin_dir, extra_env=env)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "ListenStream=127.0.0.1:2460\n" in _socket_file(tmp_path).read_text(encoding="utf-8")


def test_later_deploy_restarts_only_the_service_and_keeps_the_socket(tmp_path: Path) -> None:
    _origin, _seed, deploy = _make_deploy_fixture(tmp_path)
    bin_dir = _stub_bin(tmp_path)
    env = _layout_env(tmp_path, bin_dir)
    assert _run_deploy(tmp_path, deploy, bin_dir, extra_env=env).returncode == 0
    _clear_calls(tmp_path)

    result = _run_deploy(tmp_path, deploy, bin_dir, extra_env=env)

    assert result.returncode == 0, result.stdout + result.stderr
    calls = _calls(tmp_path)
    assert "restart codex-lb.service" in calls
    assert not [call for call in calls if call.startswith(("stop", "start"))]
    assert _state(tmp_path, "codex-lb.socket") == "active"
    assert _layout_record(tmp_path) == "socket"


def test_steady_state_restart_not_ready_falls_back_to_the_single_unit(tmp_path: Path) -> None:
    _origin, _seed, deploy = _make_deploy_fixture(tmp_path)
    bin_dir = _stub_bin(tmp_path)
    env = _layout_env(tmp_path, bin_dir)
    assert _run_deploy(tmp_path, deploy, bin_dir, extra_env=env).returncode == 0
    # The next build does not become ready on the socket.
    (tmp_path / "systemd-state" / "not-ready-on-socket").touch()
    _clear_calls(tmp_path)

    result = _run_deploy(tmp_path, deploy, bin_dir, extra_env=env)

    assert result.returncode != 0
    assert "restart codex-lb.service" in _calls(tmp_path)
    assert not _socket_file(tmp_path).exists()
    assert not _dropin_file(tmp_path).exists()
    assert _state(tmp_path, "codex-lb.socket") == "inactive"
    assert _state(tmp_path, "codex-lb.service") == "active"
    assert _layout_record(tmp_path) == "single"
    log = _read_latest_log(tmp_path)
    assert "socket layout failed: codex-lb.service did not become ready" in log
    assert "runs as a single unit again" in log


def test_socket_that_cannot_start_falls_back_to_the_single_unit(tmp_path: Path) -> None:
    _origin, _seed, deploy = _make_deploy_fixture(tmp_path)
    bin_dir = _stub_bin(tmp_path)
    env = _layout_env(tmp_path, bin_dir)
    (tmp_path / "systemd-state" / "fail-start-codex-lb.socket").touch()

    result = _run_deploy(tmp_path, deploy, bin_dir, extra_env=env)

    assert result.returncode != 0
    assert not _socket_file(tmp_path).exists()
    assert not _dropin_file(tmp_path).exists()
    assert _state(tmp_path, "codex-lb.service") == "active"
    assert _layout_record(tmp_path) == "single"
    log = _read_latest_log(tmp_path)
    assert "socket layout failed: could not start codex-lb.socket" in log
    assert "runs as a single unit again" in log
    assert "=== codex-lb deploy failed ===" in log


def test_service_not_ready_on_the_socket_falls_back_to_the_single_unit(tmp_path: Path) -> None:
    _origin, _seed, deploy = _make_deploy_fixture(tmp_path)
    bin_dir = _stub_bin(tmp_path)
    env = _layout_env(tmp_path, bin_dir)
    (tmp_path / "systemd-state" / "not-ready-on-socket").touch()

    result = _run_deploy(tmp_path, deploy, bin_dir, extra_env=env)

    assert result.returncode != 0
    assert not _socket_file(tmp_path).exists()
    assert not _dropin_file(tmp_path).exists()
    assert _state(tmp_path, "codex-lb.socket") == "inactive"
    assert _state(tmp_path, "codex-lb.service") == "active"
    assert _layout_record(tmp_path) == "single"
    log = _read_latest_log(tmp_path)
    assert "did not become ready" in log
    assert "runs as a single unit again" in log


def test_entrypoint_preflight_failure_leaves_the_running_service_alone(tmp_path: Path) -> None:
    _origin, _seed, deploy = _make_deploy_fixture(tmp_path)
    bin_dir = _stub_bin(tmp_path)
    env = _layout_env(tmp_path, bin_dir, entrypoint_ok=False)

    result = _run_deploy(tmp_path, deploy, bin_dir, extra_env=env)

    assert result.returncode != 0
    calls = _calls(tmp_path)
    assert not [call for call in calls if call.startswith(("stop", "start", "restart"))]
    assert not _socket_file(tmp_path).exists()
    assert _state(tmp_path, "codex-lb.service") == "active"
    assert "--help failed; codex-lb.service was not touched" in _read_latest_log(tmp_path)


def test_rollback_layout_returns_to_the_single_unit_and_later_deploys_keep_it(tmp_path: Path) -> None:
    _origin, _seed, deploy = _make_deploy_fixture(tmp_path)
    bin_dir = _stub_bin(tmp_path)
    env = _layout_env(tmp_path, bin_dir)
    assert _run_deploy(tmp_path, deploy, bin_dir, extra_env=env).returncode == 0

    result = _run_layout_command(tmp_path, env, "rollback-layout")

    assert result.returncode == 0, result.stdout + result.stderr
    assert not _socket_file(tmp_path).exists()
    assert not _dropin_file(tmp_path).exists()
    assert _state(tmp_path, "codex-lb.socket") == "inactive"
    assert _state(tmp_path, "codex-lb.service") == "active"
    assert _layout_record(tmp_path) == "single"
    assert "rollback success" in _read_latest_log(tmp_path)

    _clear_calls(tmp_path)
    result = _run_deploy(tmp_path, deploy, bin_dir, extra_env=env)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "restart codex-lb.service" in _calls(tmp_path)
    assert not _socket_file(tmp_path).exists()
    assert _layout_record(tmp_path) == "single"


def test_unknown_command_is_refused(tmp_path: Path) -> None:
    result = _run_layout_command(tmp_path, {}, "bogus")

    assert result.returncode == 2
    assert "usage:" in result.stderr
