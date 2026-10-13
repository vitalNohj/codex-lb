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
    assert "ERROR: deploy dir HEAD" in log
    assert "=== codex-lb deploy failed ===" in log
