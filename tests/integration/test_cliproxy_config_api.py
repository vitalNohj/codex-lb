from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.clients.claude_sidecar import ClaudeSidecarError, ClaudeSidecarUnavailableError
from app.db.models import AuditLog, CliproxyConfigSnapshot, CliproxyConfigWriteClaim
from app.db.session import SessionLocal
from app.modules.cliproxy_accounts.config_editor import REDACTED_CHANGED, REDACTED_PLACEHOLDER, REDACTION_MARK
from app.modules.cliproxy_accounts.config_write_lock import cliproxy_config_lock_key

pytestmark = pytest.mark.integration

_CLIENT_KEY = "client-live-key"
_MANAGEMENT = "mgmt-live-secret"
_GITHUB = "ghp-live-token"
_TURN_USER = "turn-live-user"
_TURN_SECRET = "turn-live-secret"
_PROXY = "socks5://proxy-user:proxy-pass@10.1.2.3:1080/"
_SECRETS = (_CLIENT_KEY, _MANAGEMENT, _GITHUB, _TURN_USER, _TURN_SECRET, "proxy-pass")

_CONFIG = f"""\
config-version: 8
server:
  port: 8317
  github-token: "{_GITHUB}"
management:
  secret-key: "{_MANAGEMENT}"
access:
  api-keys:
    - "{_CLIENT_KEY}"
routing:
  strategy: round-robin
  session-affinity: true
requests:
  proxy-url: "{_PROXY}"
providers:
  codex:
    live-media-relay:
      ice-servers:
        - urls:
            - "turn:turn.example.com:3478"
          username: "{_TURN_USER}"
          credential: "{_TURN_SECRET}"
debug: false
"""


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class _FakeConfigClient:
    yaml = _CONFIG
    puts: list[str] = []
    fetches = 0
    fail_put = False
    apply_then_timeout = False
    timeout_unconfirmed = False
    fail_next_fetch = False

    def __init__(self, _config: object) -> None:
        pass

    async def fetch_config_yaml(self) -> str:
        self.__class__.fetches += 1
        if self.__class__.fail_next_fetch:
            self.__class__.fail_next_fetch = False
            raise ClaudeSidecarUnavailableError("timed out")
        return self.__class__.yaml

    async def put_config_yaml(self, body: str) -> None:
        if self.__class__.apply_then_timeout:
            self.__class__.puts.append(body)
            self.__class__.yaml = body
            raise ClaudeSidecarUnavailableError("timed out")
        if self.__class__.timeout_unconfirmed:
            self.__class__.fail_next_fetch = True
            raise ClaudeSidecarUnavailableError("timed out")
        if self.__class__.fail_put:
            raise ClaudeSidecarError(500, "rejected")
        self.__class__.puts.append(body)
        self.__class__.yaml = body


def _reset_fake() -> None:
    _FakeConfigClient.yaml = _CONFIG
    _FakeConfigClient.puts = []
    _FakeConfigClient.fetches = 0
    _FakeConfigClient.fail_put = False
    _FakeConfigClient.apply_then_timeout = False
    _FakeConfigClient.timeout_unconfirmed = False
    _FakeConfigClient.fail_next_fetch = False


def _install_fake(monkeypatch: pytest.MonkeyPatch) -> None:
    _reset_fake()
    monkeypatch.setattr("app.modules.cliproxy_accounts.config_service.ClaudeSidecarClient", _FakeConfigClient)


async def _enable(async_client) -> None:
    response = await async_client.put(
        "/api/settings",
        json={
            "claudeSidecarEnabled": True,
            "claudeSidecarApiKey": "sidecar-key",
            "claudeSidecarManagementKey": "mgmt-key",
        },
    )
    assert response.status_code == 200


def _assert_no_secrets(text: str) -> None:
    for secret in _SECRETS:
        assert secret not in text


async def _audit_rows(action: str) -> list[AuditLog]:
    async with SessionLocal() as session:
        result = await session.execute(select(AuditLog).where(AuditLog.action == action).order_by(AuditLog.id))
        return list(result.scalars().all())


@pytest.mark.asyncio
async def test_config_view_is_redacted_and_disabled_until_the_integration_is_on(async_client, monkeypatch) -> None:
    _install_fake(monkeypatch)

    disabled = await async_client.get("/api/cliproxy/config")
    assert disabled.status_code == 200
    assert disabled.json()["status"] == "disabled"
    assert _FakeConfigClient.fetches == 0

    await _enable(async_client)
    response = await async_client.get("/api/cliproxy/config")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "healthy"
    assert payload["contentSha256"] == _sha(_CONFIG)
    assert payload["sessionAffinity"] is True
    assert payload["forceModelPrefix"] is False
    assert payload["rollbackAvailable"] is False
    assert f"{REDACTION_MARK}:0»" in payload["yaml"]
    assert "port: 8317" in payload["yaml"]
    _assert_no_secrets(response.text)


@pytest.mark.asyncio
async def test_preview_is_a_dry_run_and_confirm_round_trips_placeholders(async_client, monkeypatch) -> None:
    _install_fake(monkeypatch)
    await _enable(async_client)
    current = await async_client.get("/api/cliproxy/config")
    body = current.json()
    submitted = body["yaml"].replace("debug: false", "debug: true", 1)

    preview = await async_client.post(
        "/api/cliproxy/config/preview",
        json={"yaml": submitted, "contentSha256": body["contentSha256"]},
    )
    assert preview.status_code == 200
    preview_body = preview.json()
    assert preview_body["changed"] is True
    assert "debug: true" in preview_body["diff"]
    _assert_no_secrets(preview.text)
    assert _FakeConfigClient.puts == []

    unconfirmed = await async_client.put(
        "/api/cliproxy/config",
        json={"yaml": submitted, "contentSha256": body["contentSha256"]},
    )
    assert unconfirmed.status_code == 422
    assert _FakeConfigClient.puts == []

    replaced = await async_client.put(
        "/api/cliproxy/config",
        json={"yaml": submitted, "contentSha256": body["contentSha256"], "confirm": True},
    )
    assert replaced.status_code == 200
    replaced_body = replaced.json()
    assert replaced_body["rollbackAvailable"] is True
    assert "debug: true" in replaced_body["yaml"]
    _assert_no_secrets(replaced.text)
    assert len(_FakeConfigClient.puts) == 1
    written = _FakeConfigClient.puts[0]
    assert REDACTION_MARK not in written
    for secret in _SECRETS:
        assert secret in written
    assert "debug: true" in written
    assert "debug: false" not in written

    audits = await _audit_rows("cliproxy_config_replace")
    assert len(audits) == 1
    details = json.loads(audits[0].details or "{}")
    assert details["content_sha256_before"] == _sha(_CONFIG)
    assert details["content_sha256_after"] == _sha(written)
    _assert_no_secrets(audits[0].details or "")

    async with SessionLocal() as session:
        snapshot = (await session.execute(select(CliproxyConfigSnapshot))).scalars().one()
    assert _CLIENT_KEY.encode() not in snapshot.yaml_ciphertext
    assert snapshot.action == "replace"
    assert snapshot.content_sha256 == _sha(_CONFIG)


@pytest.mark.asyncio
async def test_a_changed_secret_is_written_without_appearing_in_the_diff(async_client, monkeypatch) -> None:
    _install_fake(monkeypatch)
    await _enable(async_client)
    current = (await async_client.get("/api/cliproxy/config")).json()
    submitted = current["yaml"].replace(f'"{REDACTION_MARK}:0»"', '"brand-new-key"', 1)

    preview = await async_client.post(
        "/api/cliproxy/config/preview",
        json={"yaml": submitted, "contentSha256": current["contentSha256"]},
    )
    assert preview.status_code == 200
    assert REDACTED_CHANGED in preview.json()["diff"]
    assert "brand-new-key" not in preview.text
    _assert_no_secrets(preview.text)

    replaced = await async_client.put(
        "/api/cliproxy/config",
        json={"yaml": submitted, "contentSha256": current["contentSha256"], "confirm": True},
    )
    assert replaced.status_code == 200
    assert "brand-new-key" not in replaced.text
    written = _FakeConfigClient.puts[0]
    assert "brand-new-key" in written
    assert _GITHUB not in written
    assert _CLIENT_KEY in written
    assert _MANAGEMENT in written
    assert REDACTION_MARK not in written


@pytest.mark.asyncio
async def test_invalid_yaml_and_a_dangling_placeholder_do_not_write(async_client, monkeypatch) -> None:
    _install_fake(monkeypatch)
    await _enable(async_client)
    current = (await async_client.get("/api/cliproxy/config")).json()

    invalid = await async_client.post(
        "/api/cliproxy/config/preview",
        json={"yaml": "routing: [\n", "contentSha256": current["contentSha256"]},
    )
    assert invalid.status_code == 400
    assert invalid.json()["error"]["code"] == "invalid_yaml"

    dangling = await async_client.put(
        "/api/cliproxy/config",
        json={
            "yaml": current["yaml"] + f'\napi-key: "{REDACTED_PLACEHOLDER}"\n',
            "contentSha256": current["contentSha256"],
            "confirm": True,
        },
    )
    assert dangling.status_code == 400
    assert dangling.json()["error"]["code"] == "redacted_placeholder"
    assert _FakeConfigClient.puts == []


@pytest.mark.asyncio
async def test_a_stale_editor_is_rejected(async_client, monkeypatch) -> None:
    _install_fake(monkeypatch)
    await _enable(async_client)
    current = (await async_client.get("/api/cliproxy/config")).json()
    _FakeConfigClient.yaml = _CONFIG.replace("debug: false", "debug: true", 1)

    response = await async_client.put(
        "/api/cliproxy/config",
        json={"yaml": current["yaml"], "contentSha256": current["contentSha256"], "confirm": True},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "config_changed"
    assert _FakeConfigClient.puts == []


@pytest.mark.asyncio
async def test_rollback_restores_the_snapshotted_file(async_client, monkeypatch) -> None:
    _install_fake(monkeypatch)
    await _enable(async_client)
    current = (await async_client.get("/api/cliproxy/config")).json()
    submitted = current["yaml"].replace("debug: false", "debug: true", 1)
    replaced = await async_client.put(
        "/api/cliproxy/config",
        json={"yaml": submitted, "contentSha256": current["contentSha256"], "confirm": True},
    )
    assert replaced.status_code == 200

    missing = await async_client.post("/api/cliproxy/config/rollback", json={})
    assert missing.status_code == 422
    live = (await async_client.get("/api/cliproxy/config")).json()
    stale = await async_client.post(
        "/api/cliproxy/config/rollback",
        json={"confirm": True, "contentSha256": current["contentSha256"]},
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "config_changed"
    assert _FakeConfigClient.yaml != _CONFIG

    restored = await async_client.post(
        "/api/cliproxy/config/rollback",
        json={"confirm": True, "contentSha256": live["contentSha256"]},
    )
    assert restored.status_code == 200
    assert restored.json()["contentSha256"] == _sha(_CONFIG)
    assert "debug: false" in restored.json()["yaml"]
    _assert_no_secrets(restored.text)
    assert _FakeConfigClient.yaml == _CONFIG
    assert REDACTION_MARK not in _FakeConfigClient.puts[-1]

    audits = await _audit_rows("cliproxy_config_rollback")
    assert len(audits) == 1
    _assert_no_secrets(audits[0].details or "")
    assert json.loads(audits[0].details or "{}")["content_sha256_after"] == _sha(_CONFIG)


@pytest.mark.asyncio
async def test_a_failed_upload_does_not_destroy_the_previous_snapshot(async_client, monkeypatch) -> None:
    _install_fake(monkeypatch)
    await _enable(async_client)
    current = (await async_client.get("/api/cliproxy/config")).json()
    first = current["yaml"].replace("debug: false", "debug: true", 1)
    assert (
        await async_client.put(
            "/api/cliproxy/config",
            json={"yaml": first, "contentSha256": current["contentSha256"], "confirm": True},
        )
    ).status_code == 200

    edited = (await async_client.get("/api/cliproxy/config")).json()
    _FakeConfigClient.fail_put = True
    failed = await async_client.put(
        "/api/cliproxy/config",
        json={
            "yaml": edited["yaml"].replace("port: 8317", "port: 9999", 1),
            "contentSha256": edited["contentSha256"],
            "confirm": True,
        },
    )
    assert failed.status_code == 502
    assert _FakeConfigClient.yaml != _CONFIG
    assert "port: 8317" in _FakeConfigClient.yaml

    _FakeConfigClient.fail_put = False
    restored = await async_client.post(
        "/api/cliproxy/config/rollback",
        json={"confirm": True, "contentSha256": edited["contentSha256"]},
    )
    assert restored.status_code == 200
    assert _FakeConfigClient.yaml == _CONFIG


@pytest.mark.asyncio
async def test_routing_flag_patches_snapshot_and_keep_the_rest_of_the_file(async_client, monkeypatch) -> None:
    _install_fake(monkeypatch)
    await _enable(async_client)
    current = (await async_client.get("/api/cliproxy/config")).json()

    unknown = await async_client.patch(
        "/api/cliproxy/config/routing/strategy",
        json={"enabled": True, "contentSha256": current["contentSha256"]},
    )
    assert unknown.status_code == 404

    patched = await async_client.patch(
        "/api/cliproxy/config/routing/force-model-prefix",
        json={"enabled": True, "contentSha256": current["contentSha256"]},
    )
    assert patched.status_code == 200
    assert patched.json()["forceModelPrefix"] is True
    _assert_no_secrets(patched.text)
    written = _FakeConfigClient.puts[0]
    assert "force-model-prefix: true" in written
    assert "session-affinity: true" in written
    for secret in _SECRETS:
        assert secret in written
    assert REDACTION_MARK not in written

    audits = await _audit_rows("cliproxy_config_routing_patch")
    assert len(audits) == 1
    details = json.loads(audits[0].details or "{}")
    assert details["field"] == "routing.force-model-prefix"
    assert details["enabled"] is True
    _assert_no_secrets(audits[0].details or "")

    affinity = await async_client.patch(
        "/api/cliproxy/config/routing/session-affinity",
        json={"enabled": False, "contentSha256": patched.json()["contentSha256"]},
    )
    assert affinity.status_code == 200
    assert affinity.json()["sessionAffinity"] is False
    assert "session-affinity: false" in _FakeConfigClient.yaml
    assert "force-model-prefix: true" in _FakeConfigClient.yaml
    assert _MANAGEMENT in _FakeConfigClient.yaml


@pytest.mark.asyncio
async def test_create_writes_a_new_document_and_rejects_a_placeholder_with_no_secret(async_client, monkeypatch) -> None:
    _install_fake(monkeypatch)
    _FakeConfigClient.yaml = ""
    await _enable(async_client)
    current = (await async_client.get("/api/cliproxy/config")).json()
    assert current["yaml"] == ""

    rejected = await async_client.put(
        "/api/cliproxy/config",
        json={
            "yaml": f'management:\n  secret-key: "{REDACTED_PLACEHOLDER}"\n',
            "contentSha256": current["contentSha256"],
            "confirm": True,
        },
    )
    assert rejected.status_code == 400
    assert _FakeConfigClient.puts == []

    created = await async_client.put(
        "/api/cliproxy/config",
        json={
            "yaml": 'management:\n  secret-key: "fresh-secret"\n',
            "contentSha256": current["contentSha256"],
            "confirm": True,
        },
    )
    assert created.status_code == 200
    assert "fresh-secret" not in created.text
    assert _FakeConfigClient.yaml == 'management:\n  secret-key: "fresh-secret"\n'


@pytest.mark.asyncio
async def test_a_live_write_lease_rejects_a_second_replace(async_client, monkeypatch) -> None:
    _install_fake(monkeypatch)
    await _enable(async_client)
    current = (await async_client.get("/api/cliproxy/config")).json()
    submitted = current["yaml"].replace("debug: false", "debug: true", 1)
    async with SessionLocal() as session:
        session.add(
            CliproxyConfigWriteClaim(
                lock_key=cliproxy_config_lock_key("http://127.0.0.1:8317"),
                holder_id="other-worker",
                expires_at=datetime.now(UTC) + timedelta(seconds=30),
            )
        )
        await session.commit()

    blocked = await async_client.put(
        "/api/cliproxy/config",
        json={"yaml": submitted, "contentSha256": current["contentSha256"], "confirm": True},
    )
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "config_write_busy"
    assert _FakeConfigClient.puts == []


@pytest.mark.asyncio
async def test_a_timeout_after_the_file_changes_keeps_that_rollback_point(async_client, monkeypatch) -> None:
    _install_fake(monkeypatch)
    await _enable(async_client)
    current = (await async_client.get("/api/cliproxy/config")).json()
    first = current["yaml"].replace("debug: false", "debug: true", 1)
    assert (
        await async_client.put(
            "/api/cliproxy/config",
            json={"yaml": first, "contentSha256": current["contentSha256"], "confirm": True},
        )
    ).status_code == 200
    applied = _FakeConfigClient.yaml

    edited = (await async_client.get("/api/cliproxy/config")).json()
    _FakeConfigClient.apply_then_timeout = True
    timed_out = await async_client.put(
        "/api/cliproxy/config",
        json={
            "yaml": edited["yaml"].replace("port: 8317", "port: 9999", 1),
            "contentSha256": edited["contentSha256"],
            "confirm": True,
        },
    )
    assert timed_out.status_code == 200
    assert "port: 9999" in _FakeConfigClient.yaml

    async with SessionLocal() as session:
        snapshot = (await session.execute(select(CliproxyConfigSnapshot))).scalars().one()
    assert snapshot.content_sha256 == _sha(applied)

    _FakeConfigClient.apply_then_timeout = False
    restored = await async_client.post(
        "/api/cliproxy/config/rollback",
        json={"confirm": True, "contentSha256": _sha(_FakeConfigClient.yaml)},
    )
    assert restored.status_code == 200
    assert _FakeConfigClient.yaml == applied


@pytest.mark.asyncio
async def test_an_unconfirmed_timeout_keeps_the_pre_upload_snapshot(async_client, monkeypatch) -> None:
    _install_fake(monkeypatch)
    await _enable(async_client)
    current = (await async_client.get("/api/cliproxy/config")).json()
    first = current["yaml"].replace("debug: false", "debug: true", 1)
    assert (
        await async_client.put(
            "/api/cliproxy/config",
            json={"yaml": first, "contentSha256": current["contentSha256"], "confirm": True},
        )
    ).status_code == 200
    applied = _FakeConfigClient.yaml

    edited = (await async_client.get("/api/cliproxy/config")).json()
    _FakeConfigClient.timeout_unconfirmed = True
    failed = await async_client.put(
        "/api/cliproxy/config",
        json={
            "yaml": edited["yaml"].replace("port: 8317", "port: 9999", 1),
            "contentSha256": edited["contentSha256"],
            "confirm": True,
        },
    )
    assert failed.status_code == 503
    assert _FakeConfigClient.yaml == applied

    async with SessionLocal() as session:
        snapshot = (await session.execute(select(CliproxyConfigSnapshot))).scalars().one()
    assert snapshot.content_sha256 == _sha(applied)
    assert snapshot.content_sha256 != _sha(_CONFIG)
    assert snapshot.upstream_key == cliproxy_config_lock_key("http://127.0.0.1:8317")


@pytest.mark.asyncio
async def test_rollback_stays_on_the_upstream_that_saved_it(async_client, monkeypatch) -> None:
    _install_fake(monkeypatch)
    await _enable(async_client)
    current = (await async_client.get("/api/cliproxy/config")).json()
    submitted = current["yaml"].replace("debug: false", "debug: true", 1)
    assert (
        await async_client.put(
            "/api/cliproxy/config",
            json={"yaml": submitted, "contentSha256": current["contentSha256"], "confirm": True},
        )
    ).status_code == 200
    puts_before_move = list(_FakeConfigClient.puts)

    moved = await async_client.put("/api/settings", json={"claudeSidecarBaseUrl": "http://127.0.0.1:9999"})
    assert moved.status_code == 200
    other = await async_client.get("/api/cliproxy/config")
    assert other.json()["rollbackAvailable"] is False
    blocked = await async_client.post(
        "/api/cliproxy/config/rollback",
        json={"confirm": True, "contentSha256": other.json()["contentSha256"]},
    )
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "nothing_to_rollback"
    assert _FakeConfigClient.puts == puts_before_move

    restored_settings = await async_client.put(
        "/api/settings",
        json={"claudeSidecarBaseUrl": "http://127.0.0.1:8317"},
    )
    assert restored_settings.status_code == 200
    home = await async_client.get("/api/cliproxy/config")
    assert home.json()["rollbackAvailable"] is True
