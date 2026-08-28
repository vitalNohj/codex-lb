from __future__ import annotations

import pytest

from app.core.clients.claude_sidecar import SidecarModel
from app.core.clients.orcarouter_sidecar import (
    OrcaRouterSidecarClient,
    OrcaRouterSidecarError,
    OrcaRouterSidecarUnavailableError,
    reset_orcarouter_sidecar_client_cache,
)

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _clear_orcarouter_client_cache():
    reset_orcarouter_sidecar_client_cache()
    yield
    reset_orcarouter_sidecar_client_cache()


class _FakeOrcaRouterClient:
    error: Exception | None = None
    models = [SidecarModel(id="orcarouter/auto", created=123, owned_by="deepseek")]

    def __init__(self, _config) -> None:
        pass

    async def list_models(self):
        if self.error is not None:
            raise self.error
        return list(self.models)

    async def list_models_cached(self):
        return await self.list_models()


@pytest.mark.asyncio
async def test_orcarouter_sidecar_status_reports_disabled_and_missing_api_key(async_client):
    response = await async_client.put(
        "/api/settings",
        json={
            "orcarouterSidecarEnabled": False,
            "orcarouterSidecarClearApiKey": True,
        },
    )
    assert response.status_code == 200

    response = await async_client.get("/api/orcarouter-sidecar/status")
    assert response.status_code == 200
    assert response.json()["status"] == "disabled"

    response = await async_client.put(
        "/api/settings",
        json={
            "orcarouterSidecarEnabled": True,
            "orcarouterSidecarClearApiKey": True,
        },
    )
    assert response.status_code == 200

    response = await async_client.get("/api/orcarouter-sidecar/status")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "missing_api_key"
    assert payload["configured"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "expected_status"),
    [
        (OrcaRouterSidecarUnavailableError("connection refused"), "unreachable"),
        (OrcaRouterSidecarError(401, "bad key"), "unauthorized"),
        (OrcaRouterSidecarError(500, "sidecar exploded"), "error"),
    ],
)
async def test_orcarouter_sidecar_test_connection_records_error_statuses(
    async_client,
    monkeypatch,
    error,
    expected_status,
):
    monkeypatch.setattr(
        "app.modules.orcarouter_sidecar.service.get_orcarouter_sidecar_client",
        _FakeOrcaRouterClient,
    )
    _FakeOrcaRouterClient.error = error
    response = await async_client.put(
        "/api/settings",
        json={
            "orcarouterSidecarEnabled": True,
            "orcarouterSidecarApiKey": "orcarouter-key",
        },
    )
    assert response.status_code == 200

    response = await async_client.post("/api/orcarouter-sidecar/test")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == expected_status
    assert payload["modelCount"] is None

    status = await async_client.get("/api/orcarouter-sidecar/status")
    assert status.status_code == 200
    assert status.json()["status"] == expected_status


@pytest.mark.asyncio
async def test_orcarouter_sidecar_test_connection_records_healthy_and_lists_models(async_client, monkeypatch):
    monkeypatch.setattr(
        "app.modules.orcarouter_sidecar.service.get_orcarouter_sidecar_client",
        _FakeOrcaRouterClient,
    )
    _FakeOrcaRouterClient.error = None
    _FakeOrcaRouterClient.models = [SidecarModel(id="orcarouter/auto", created=123, owned_by="deepseek")]
    response = await async_client.put(
        "/api/settings",
        json={
            "orcarouterSidecarEnabled": True,
            "orcarouterSidecarApiKey": "orcarouter-key",
        },
    )
    assert response.status_code == 200

    response = await async_client.post("/api/orcarouter-sidecar/test")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "healthy"
    assert payload["modelCount"] == 1
    assert payload["models"] == [{"id": "orcarouter/auto", "created": 123, "ownedBy": "deepseek"}]

    response = await async_client.get("/api/orcarouter-sidecar/models")
    assert response.status_code == 200
    assert response.json()["models"] == [{"id": "orcarouter/auto", "created": 123, "ownedBy": "deepseek"}]


# Not a real credential: a synthetic string shaped like an OrcaRouter key so the
# assertion below proves the sanitizer removed it.
_FAKE_ORCAROUTER_KEY = "sk-orca-NOTAREALKEY000000000"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "upstream_message",
    [
        "Unauthorized for Authorization: Bearer {key}",
        "rejected header bearer {key}",
        'upstream echoed {{"authorization":"Bearer {key}"}}',
        "BEARER  {key}!",
        "Invalid API key: {key}",
    ],
)
async def test_orcarouter_test_connection_never_persists_the_bearer_token(
    async_client,
    monkeypatch,
    upstream_message,
):
    """An upstream that echoes the Authorization header must not leak the key.

    ``test_connection`` writes this message to
    ``orcarouter_sidecar_last_health_message`` and the dashboard renders it, so a
    surviving token would be visible to every dashboard viewer and durable in the
    database.
    """

    monkeypatch.setattr(
        "app.modules.orcarouter_sidecar.service.get_orcarouter_sidecar_client",
        _FakeOrcaRouterClient,
    )
    _FakeOrcaRouterClient.error = OrcaRouterSidecarError(401, upstream_message.format(key=_FAKE_ORCAROUTER_KEY))

    response = await async_client.put(
        "/api/settings",
        json={
            "orcarouterSidecarEnabled": True,
            "orcarouterSidecarApiKey": _FAKE_ORCAROUTER_KEY,
        },
    )
    assert response.status_code == 200

    test_payload = (await async_client.post("/api/orcarouter-sidecar/test")).json()
    assert test_payload["status"] == "unauthorized"
    assert _FAKE_ORCAROUTER_KEY not in test_payload["message"]
    assert "[redacted]" in test_payload["message"]

    # The persisted column is replayed by the status endpoint on every load.
    status_payload = (await async_client.get("/api/orcarouter-sidecar/status")).json()
    assert _FAKE_ORCAROUTER_KEY not in status_payload["message"]

    from sqlalchemy import select

    from app.db.models import DashboardSettings
    from app.db.session import SessionLocal

    async with SessionLocal() as session:
        stored = (await session.execute(select(DashboardSettings.orcarouter_sidecar_last_health_message))).scalar_one()
    assert _FAKE_ORCAROUTER_KEY not in str(stored)


# Not a real credential: a synthetic colon-delimited value, the shape schemes
# that namespace their keys ("<env>:<id>:<secret>") issue. Nothing constrains the
# stored key format, so an operator can configure this today.
_FAKE_PUNCTUATED_ORCAROUTER_KEY = "notarealorca:live:0123456789abcdef"
_FAKE_PUNCTUATED_KEY_TAIL = "0123456789abcdef"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "upstream_message",
    [
        "Invalid credential {key} for project",
        "invalid api_key={key}",
        "Invalid credential {key}.",
        '{{"authorization":"Bearer {key}"}}',
    ],
)
async def test_orcarouter_test_connection_never_persists_a_punctuated_key(
    async_client,
    monkeypatch,
    upstream_message,
):
    """A configured key carrying ':' is still a credential on the health path."""

    monkeypatch.setattr(
        "app.modules.orcarouter_sidecar.service.get_orcarouter_sidecar_client",
        _FakeOrcaRouterClient,
    )
    _FakeOrcaRouterClient.error = OrcaRouterSidecarError(
        401,
        upstream_message.format(key=_FAKE_PUNCTUATED_ORCAROUTER_KEY),
    )

    response = await async_client.put(
        "/api/settings",
        json={
            "orcarouterSidecarEnabled": True,
            "orcarouterSidecarApiKey": _FAKE_PUNCTUATED_ORCAROUTER_KEY,
        },
    )
    assert response.status_code == 200

    test_payload = (await async_client.post("/api/orcarouter-sidecar/test")).json()
    assert _FAKE_PUNCTUATED_ORCAROUTER_KEY not in test_payload["message"]
    assert _FAKE_PUNCTUATED_KEY_TAIL not in test_payload["message"]
    assert "[redacted]" in test_payload["message"]

    status_payload = (await async_client.get("/api/orcarouter-sidecar/status")).json()
    assert _FAKE_PUNCTUATED_KEY_TAIL not in status_payload["message"]

    from sqlalchemy import select

    from app.db.models import DashboardSettings
    from app.db.session import SessionLocal

    async with SessionLocal() as session:
        stored = (await session.execute(select(DashboardSettings.orcarouter_sidecar_last_health_message))).scalar_one()
    assert _FAKE_PUNCTUATED_KEY_TAIL not in str(stored)


# A configured value that is not credential-shaped and also appears as an
# ordinary English word in upstream prose.
_NON_CREDENTIAL_CONFIGURED_VALUE = "key"
_ORDINARY_UPSTREAM_MESSAGE = "Invalid API key"


@pytest.mark.asyncio
async def test_orcarouter_test_connection_relays_ordinary_upstream_text_unchanged(async_client, monkeypatch):
    """Sanitizing must not garble a message that carries no credential.

    Removing the configured value verbatim and unanchored rewrote an upstream
    ``Invalid API key`` into ``Invalid API [redacted]`` whenever the configured
    value happened to be a short ordinary word.
    """

    monkeypatch.setattr(
        "app.modules.orcarouter_sidecar.service.get_orcarouter_sidecar_client",
        _FakeOrcaRouterClient,
    )
    _FakeOrcaRouterClient.error = OrcaRouterSidecarError(500, _ORDINARY_UPSTREAM_MESSAGE)

    response = await async_client.put(
        "/api/settings",
        json={
            "orcarouterSidecarEnabled": True,
            "orcarouterSidecarApiKey": _NON_CREDENTIAL_CONFIGURED_VALUE,
        },
    )
    assert response.status_code == 200

    test_payload = (await async_client.post("/api/orcarouter-sidecar/test")).json()

    assert test_payload["message"] == _ORDINARY_UPSTREAM_MESSAGE


@pytest.mark.asyncio
async def test_settings_models_endpoint_reuses_the_orcarouter_models_cache(async_client, monkeypatch):
    """Opening Settings -> OrcaRouter must not block on a fresh upstream fetch.

    ``list_models_cached`` keeps its TTL state on the client instance, so an
    inline client per request made ``orcarouter_sidecar_models_cache_ttl_seconds``
    dead: every render paid another round trip of up to
    ``request_timeout_seconds``.
    """

    upstream_fetches = 0

    async def _counting_list_models(_self):
        nonlocal upstream_fetches
        upstream_fetches += 1
        return [SidecarModel(id="orcarouter/auto", created=123, owned_by="deepseek")]

    monkeypatch.setattr(OrcaRouterSidecarClient, "list_models", _counting_list_models)

    response = await async_client.put(
        "/api/settings",
        json={
            "orcarouterSidecarEnabled": True,
            "orcarouterSidecarApiKey": "orcarouter-key",
            "orcarouterSidecarModelsCacheTtlSeconds": 60,
        },
    )
    assert response.status_code == 200

    for _ in range(3):
        models = await async_client.get("/api/orcarouter-sidecar/models")
        assert models.status_code == 200
        assert models.json()["models"] == [{"id": "orcarouter/auto", "created": 123, "ownedBy": "deepseek"}]

    assert upstream_fetches == 1

    # The dashboard model-source picker shares the same cache.
    picker = await async_client.get("/api/models")
    assert picker.status_code == 200
    assert "orcarouter/auto" in [entry["id"] for entry in picker.json()["models"]]
    assert upstream_fetches == 1


@pytest.mark.asyncio
async def test_rotating_the_orcarouter_key_evicts_the_cached_models_client(async_client, monkeypatch):
    """A credential change must never be served by a client holding the old key."""

    seen_keys: list[str | None] = []

    async def _recording_list_models(self):
        seen_keys.append(self.config.api_key)
        return [SidecarModel(id="orcarouter/auto", created=123, owned_by="deepseek")]

    monkeypatch.setattr(OrcaRouterSidecarClient, "list_models", _recording_list_models)

    await async_client.put(
        "/api/settings",
        json={
            "orcarouterSidecarEnabled": True,
            "orcarouterSidecarApiKey": "first-key",
            "orcarouterSidecarModelsCacheTtlSeconds": 60,
        },
    )
    assert (await async_client.get("/api/orcarouter-sidecar/models")).status_code == 200

    await async_client.put("/api/settings", json={"orcarouterSidecarApiKey": "rotated-key"})
    assert (await async_client.get("/api/orcarouter-sidecar/models")).status_code == 200

    assert seen_keys == ["first-key", "rotated-key"]


# Synthetic, deliberately shorter than the 16-character threshold that applies to
# purely alphabetic values. Not a real credential.
_FAKE_SHORT_ORCAROUTER_KEY = "sk-x1y2z3"
# Synthetic all-letter key, long enough that no ordinary upstream message would
# contain it by coincidence. Not a real credential.
_FAKE_ALPHABETIC_ORCAROUTER_KEY = "notarealorcakeyalphabeticvalue"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "configured_key",
    [_FAKE_SHORT_ORCAROUTER_KEY, _FAKE_ALPHABETIC_ORCAROUTER_KEY],
)
@pytest.mark.parametrize(
    "upstream_message",
    [
        "rejected token {key}",
        "Invalid credential {key}.",
        "upstream said {key} is not valid",
    ],
)
async def test_short_configured_key_is_redacted_even_when_echoed_bare(
    async_client,
    monkeypatch,
    upstream_message,
    configured_key,
):
    """An opaque configured key is a secret whatever its shape or length.

    A length-only gate let a short mixed-shape key through, and a shape-only gate
    let a long all-letter key through. Either way a key echoed without a
    ``bearer``/``api key`` label survived into
    ``orcarouter_sidecar_last_health_message`` and the dashboard status response.
    """

    monkeypatch.setattr(
        "app.modules.orcarouter_sidecar.service.get_orcarouter_sidecar_client",
        _FakeOrcaRouterClient,
    )
    _FakeOrcaRouterClient.error = OrcaRouterSidecarError(401, upstream_message.format(key=configured_key))

    response = await async_client.put(
        "/api/settings",
        json={
            "orcarouterSidecarEnabled": True,
            "orcarouterSidecarApiKey": configured_key,
        },
    )
    assert response.status_code == 200

    test_payload = (await async_client.post("/api/orcarouter-sidecar/test")).json()
    assert configured_key not in test_payload["message"]
    assert "[redacted]" in test_payload["message"]

    status_payload = (await async_client.get("/api/orcarouter-sidecar/status")).json()
    assert configured_key not in status_payload["message"]

    from sqlalchemy import select

    from app.db.models import DashboardSettings
    from app.db.session import SessionLocal

    async with SessionLocal() as session:
        stored = (await session.execute(select(DashboardSettings.orcarouter_sidecar_last_health_message))).scalar_one()
    assert configured_key not in str(stored)


@pytest.mark.asyncio
async def test_alphabetic_configured_value_leaves_ordinary_prose_byte_exact(
    async_client,
    monkeypatch,
):
    """Redacting by shape must not garble upstream prose.

    A purely alphabetic configured value is ambiguous with an ordinary word, so
    it stays label-gated: ``Invalid API key`` must survive byte for byte while a
    credential-positioned occurrence is still removed.
    """

    monkeypatch.setattr(
        "app.modules.orcarouter_sidecar.service.get_orcarouter_sidecar_client",
        _FakeOrcaRouterClient,
    )
    _FakeOrcaRouterClient.error = OrcaRouterSidecarError(401, "Invalid API key")

    response = await async_client.put(
        "/api/settings",
        json={"orcarouterSidecarEnabled": True, "orcarouterSidecarApiKey": "key"},
    )
    assert response.status_code == 200

    test_payload = (await async_client.post("/api/orcarouter-sidecar/test")).json()
    assert test_payload["message"] == "Invalid API key"
