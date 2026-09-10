"""OmniRoute is disabled as a product integration.

The implementation modules are retained dormant for a future re-enable, so
these tests assert *product* behaviour through the real end-user API surfaces:
OmniRoute is invisible, unreachable, and unusable even when stored dashboard
settings and environment variables still enable it, while the neighbouring
sidecar integrations keep working.

Nothing here inspects implementation source; every assertion goes through an
externally callable route.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import aiohttp
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.clients.orcarouter_sidecar import OrcaRouterSidecarConfig
from app.core.config.settings import get_settings
from app.core.crypto import TokenEncryptor
from app.db.models import DashboardSettings, RequestLog
from app.db.session import SessionLocal
from app.modules.api_keys.repository import ApiKeysRepository
from app.modules.api_keys.service import ApiKeyCreateData, ApiKeysService
from app.modules.omniroute_sidecar.service import OmniRouteSidecarService
from app.modules.proxy.omniroute_sidecar_dispatch import omniroute_sidecar_config_from_settings
from app.modules.settings.repository import SettingsRepository

pytestmark = pytest.mark.integration

OMNIROUTE_MODEL = "omniroute/test-chat"
ORCAROUTER_MODEL = "orcarouter/auto"


@dataclass(frozen=True, slots=True)
class _FakeModel:
    id: str
    created: int | None = 123
    owned_by: str | None = "orcarouter"


class _FakeOrcaRouterClient:
    """Minimal OrcaRouter double proving a neighbouring integration still works."""

    def __init__(self, config: OrcaRouterSidecarConfig) -> None:
        self.config = config
        self.chat_payloads: list[dict] = []
        self.models = [_FakeModel(ORCAROUTER_MODEL)]

    async def list_models_cached(self):
        return self.models

    async def chat_completion(self, payload):
        self.chat_payloads.append(dict(payload))
        return {
            "id": "chatcmpl-orcarouter",
            "object": "chat.completion",
            "model": payload["model"],
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "hi"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }


class _ExplodingOmniRouteClient:
    """Fails loudly if any code path still constructs an OmniRoute client."""

    def __init__(self, _config) -> None:
        raise AssertionError("OmniRoute client constructed while the capability is disabled")


@pytest.fixture
async def stored_omniroute_configuration():
    """Persist an enabled OmniRoute configuration directly in the database.

    Writes go straight to the row because the settings API refuses OmniRoute
    fields; this models a database migrated from a release where OmniRoute was
    enabled, plus the environment variable still being set.
    """

    async with SessionLocal() as session:
        settings = (await session.execute(select(DashboardSettings))).scalars().first()
        assert settings is not None
        settings.omniroute_sidecar_enabled = True
        # Deliberately not the schema default, so a response that echoes the
        # stored value is distinguishable from one filled in by the default.
        settings.omniroute_sidecar_base_url = "http://stored-omniroute.internal:20999/v1"
        settings.omniroute_sidecar_api_key_encrypted = b"stored-omniroute-key"
        settings.omniroute_sidecar_selected_models_json = f'["{OMNIROUTE_MODEL}"]'
        settings.omniroute_sidecar_prefixes_json = '[{"prefix": "omniroute/", "strip": false}]'
        settings.omniroute_sidecar_connect_timeout_seconds = 3.25
        settings.omniroute_sidecar_request_timeout_seconds = 451.5
        settings.omniroute_sidecar_models_cache_ttl_seconds = 73.0
        settings.omniroute_sidecar_default_reasoning_effort = "high"
        settings.omniroute_sidecar_last_health_status = "healthy"
        settings.omniroute_sidecar_last_health_message = "OmniRoute sidecar reachable"
        settings.omniroute_sidecar_last_model_count = 1
        await session.commit()

    from app.core.config.settings_cache import get_settings_cache

    await get_settings_cache().invalidate()
    yield
    await get_settings_cache().invalidate()


@pytest.fixture
async def omniroute_environment_enabled(monkeypatch):
    monkeypatch.setenv("CODEX_LB_OMNIROUTE_SIDECAR_ENABLED", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
async def no_omniroute_network(monkeypatch):
    """Turn any OmniRoute client construction into a hard failure."""

    monkeypatch.setattr("app.modules.proxy.api.OmniRouteSidecarClient", _ExplodingOmniRouteClient)
    monkeypatch.setattr("app.modules.dashboard.api.OmniRouteSidecarClient", _ExplodingOmniRouteClient)


@pytest.fixture
async def fake_orcarouter(monkeypatch):
    config = OrcaRouterSidecarConfig(
        enabled=True,
        base_url="https://api.orcarouter.ai/v1",
        api_key="orca-key",
        prefixes=(),
        full_models=(ORCAROUTER_MODEL,),
        connect_timeout_seconds=8.0,
        request_timeout_seconds=600.0,
        models_cache_ttl_seconds=60.0,
    )
    client = _FakeOrcaRouterClient(config)

    async def load_config():
        return config

    monkeypatch.setattr("app.modules.proxy.api.load_orcarouter_sidecar_config", load_config)
    monkeypatch.setattr("app.modules.proxy.api.OrcaRouterSidecarClient", lambda _config: client)
    return client


# Transports the catalog handler can reach, by the exact name it looks up.
# OmniRoute is deliberately NOT listed: ``no_omniroute_network`` binds it to an
# exploding stand-in and that binding must survive, so an OmniRoute client is
# never permitted here rather than merely refused by this guard. The OrcaRouter
# class and factory are absent because the neighbour fake is the expected
# transport for this control.
_CATALOG_CONTROL_REFUSED: tuple[str, ...] = (
    "ClaudeSidecarClient",
    "OpenRouterSidecarClient",
    "OllamaSidecarClient",
    "_source_chat_completion_response",
    "collect_chat_completion",
    "_probe_chat_stream_startup_error",
)


class _UnexpectedTransport(Exception):
    """A transport other than the expected OrcaRouter neighbour was built."""


@pytest.fixture
def block_unexpected_transports(monkeypatch):
    """Refuse every reachable transport except the expected OrcaRouter fake."""

    def _refuse(name: str):
        def _factory(*args, **kwargs):
            del args, kwargs
            raise _UnexpectedTransport(name)

        return _factory

    for name in _CATALOG_CONTROL_REFUSED:
        monkeypatch.setattr(f"app.modules.proxy.api.{name}", _refuse(name), raising=True)

    from app.modules.proxy.service import ProxyService

    monkeypatch.setattr(ProxyService, "stream_responses", _refuse("ProxyService.stream_responses"), raising=True)


@pytest_asyncio.fixture
async def lifespan_free_client(
    _reset_db_state,
    block_unexpected_transports,
    no_omniroute_network,
    fake_orcarouter,
    monkeypatch,
):
    """Real routers, middleware and temp database, without the app lifespan.

    ``no_omniroute_network`` is declared as a parameter so the exploding
    OmniRoute binding is established and then left intact - the disable is what
    this control tests, so an OmniRoute client is never made reachable. The
    OrcaRouter neighbour fake is re-applied last, on both the class and the
    ``get_orcarouter_sidecar_client`` factory the catalog path actually resolves
    (api.py:4076), so the request cannot reach a real or previously cached
    client whatever the module-global cache holds.

    The settings row is seeded here because ``stored_omniroute_configuration``
    runs after this fixture and asserts the row already exists. Under the shared
    ``async_client`` the app lifespan creates it on the way up
    (``ensure_auto_bootstrap_token`` -> ``get_or_create``, main.py:354);
    ``create_app`` alone touches no database, and ``_reset_db_state`` has just
    dropped and recreated the schema. Seeding through the product's own
    ``SettingsRepository.get_or_create`` reproduces exactly that call against
    the real temporary database, rather than hand-building a row.
    """
    del _reset_db_state, block_unexpected_transports, no_omniroute_network
    import app.modules.proxy.api as proxy_api
    from app.main import create_app

    monkeypatch.setattr(
        "app.modules.proxy.api.OrcaRouterSidecarClient",
        lambda _config: fake_orcarouter,
        raising=True,
    )
    monkeypatch.setattr(
        "app.modules.proxy.api.get_orcarouter_sidecar_client",
        lambda _config: fake_orcarouter,
        raising=True,
    )

    app = create_app()

    # ``get_or_create`` COMMITs the row it inserts (repository.py:194-204), and
    # ``SessionLocal`` is the same factory the later fixture opens its own
    # session from (db/session.py:339), so the committed row is visible there.
    async with SessionLocal() as session:
        await SettingsRepository(session).get_or_create()

    async def _drain_proxy_persistence(response) -> None:
        del response
        service = getattr(app.state, "proxy_service", None)
        if service is not None and hasattr(service, "drain_persistence_tasks"):
            await service.drain_persistence_tasks(timeout_seconds=5)

    assert proxy_api.__file__.startswith(str(Path(__file__).resolve().parents[2])), (
        f"app module resolved outside this task copy: {proxy_api.__file__}"
    )
    assert proxy_api.OrcaRouterSidecarClient(fake_orcarouter.config) is fake_orcarouter
    assert proxy_api.get_orcarouter_sidecar_client(fake_orcarouter.config) is fake_orcarouter
    # The OmniRoute binding must still be the exploding stand-in, not a fake.
    assert proxy_api.OmniRouteSidecarClient is _ExplodingOmniRouteClient
    for name in _CATALOG_CONTROL_REFUSED:
        with pytest.raises(_UnexpectedTransport):
            getattr(proxy_api, name)()

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://testserver",
        event_hooks={"response": [_drain_proxy_persistence]},
    ) as client:
        yield client


async def _enable_api_key_auth(async_client) -> None:
    response = await async_client.put("/api/settings", json={"apiKeyAuthEnabled": True})
    assert response.status_code == 200


async def _create_api_key(name: str, *, allowed_models: list[str] | None = None):
    async with SessionLocal() as session:
        service = ApiKeysService(ApiKeysRepository(session))
        return await service.create_key(ApiKeyCreateData(name=name, allowed_models=allowed_models))


@pytest.mark.asyncio
async def test_runtime_capabilities_reports_omniroute_disabled(async_client):
    response = await async_client.get("/api/runtime/capabilities")

    assert response.status_code == 200
    assert response.json()["omniroute"] is False


@pytest.mark.asyncio
async def test_dormant_factory_and_service_fail_closed_without_network(
    async_client,
    monkeypatch,
    stored_omniroute_configuration,
):
    requested_urls: list[str] = []

    async def record_request(_session, _method, url, **_kwargs):
        requested_urls.append(str(url))
        raise AssertionError("unexpected outbound HTTP request")

    def reject_decryption(_encryptor, _encrypted):
        raise AssertionError("stored OmniRoute credential was decrypted")

    monkeypatch.setattr(aiohttp.ClientSession, "_request", record_request)
    monkeypatch.setattr(TokenEncryptor, "decrypt", reject_decryption)

    async with SessionLocal() as session:
        settings = (await session.execute(select(DashboardSettings))).scalars().first()
        assert settings is not None

        with pytest.raises(RuntimeError, match="capability is disabled"):
            omniroute_sidecar_config_from_settings(settings)

        service = OmniRouteSidecarService(SettingsRepository(session))
        test_result = await service.test_connection()
        models_result = await service.list_models()

    assert test_result.enabled is False
    assert test_result.status == "disabled"
    assert test_result.models == []
    assert models_result.models == []
    assert requested_urls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/omniroute-sidecar/status"),
        ("GET", "/api/omniroute-sidecar/models"),
        ("POST", "/api/omniroute-sidecar/test"),
    ],
)
async def test_omniroute_dashboard_routes_are_not_mounted(
    async_client,
    method,
    path,
    stored_omniroute_configuration,
    no_omniroute_network,
):
    """The OmniRoute status/test/models routes are unreachable.

    The neighbouring OrcaRouter equivalents answer 200 on the same shapes, so
    an unroutable status here is the disable taking effect, not a broken suite.
    """

    response = await async_client.request(method, path)

    assert response.status_code != 200
    assert "omniroute" not in response.text.lower()

    neighbour = await async_client.request(method, path.replace("omniroute", "orcarouter"))
    assert neighbour.status_code == 200


@pytest.mark.asyncio
async def test_settings_response_never_advertises_stored_omniroute_configuration(
    async_client,
    stored_omniroute_configuration,
):
    response = await async_client.get("/api/settings")

    assert response.status_code == 200
    payload = response.json()
    assert payload["omnirouteSidecarEnabled"] is False
    assert payload["omnirouteSidecarApiKeyConfigured"] is False
    assert payload["omnirouteSidecarFullModels"] == []
    assert payload["omnirouteSidecarSelectedModels"] == []
    assert payload["omnirouteSidecarModelPrefixes"] == []
    assert payload["omnirouteSidecarLastHealthStatus"] is None
    assert payload["omnirouteSidecarLastModelCount"] is None
    # Inert transport values are echoed from storage rather than omitted: an
    # omitted field would be replaced by the response model's schema default,
    # fabricating configuration that does not match the retained row.
    assert payload["omnirouteSidecarBaseUrl"] == "http://stored-omniroute.internal:20999/v1"
    assert payload["omnirouteSidecarConnectTimeoutSeconds"] == 3.25
    assert payload["omnirouteSidecarRequestTimeoutSeconds"] == 451.5
    assert payload["omnirouteSidecarModelsCacheTtlSeconds"] == 73.0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        {"omnirouteSidecarEnabled": True},
        {"omnirouteSidecarApiKey": "new-key"},
        {"omnirouteSidecarFullModels": [OMNIROUTE_MODEL]},
        {"omnirouteSidecarSelectedModels": [OMNIROUTE_MODEL]},
        {"omnirouteSidecarModelPrefixes": [{"prefix": "omniroute/", "strip": False}]},
    ],
)
async def test_settings_update_rejects_omniroute_fields(async_client, body):
    response = await async_client.put("/api/settings", json=body)

    assert response.status_code == 400
    assert "omniroute" in response.text.lower()


@pytest.mark.asyncio
async def test_settings_update_still_accepts_neighbouring_integrations(async_client):
    response = await async_client.put(
        "/api/settings",
        json={
            "orcarouterSidecarEnabled": True,
            "orcarouterSidecarApiKey": "sk-orca-test",
            "ollamaSidecarEnabled": True,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["orcarouterSidecarEnabled"] is True
    assert payload["orcarouterSidecarApiKeyConfigured"] is True
    assert payload["ollamaSidecarEnabled"] is True


@pytest.mark.asyncio
async def test_stored_omniroute_configuration_is_preserved_in_the_database(
    async_client,
    stored_omniroute_configuration,
):
    """A rejected write and a hidden response must not erase persisted rows."""

    await async_client.put("/api/settings", json={"omnirouteSidecarEnabled": True})
    await async_client.get("/api/settings")

    async with SessionLocal() as session:
        settings = (await session.execute(select(DashboardSettings))).scalars().first()
        assert settings is not None
        assert settings.omniroute_sidecar_enabled is True
        assert settings.omniroute_sidecar_api_key_encrypted == b"stored-omniroute-key"
        assert OMNIROUTE_MODEL in (settings.omniroute_sidecar_selected_models_json or "")


@pytest.mark.asyncio
async def test_settings_get_put_round_trip_preserves_stored_omniroute_configuration(
    async_client,
    stored_omniroute_configuration,
):
    response = await async_client.get("/api/settings")
    assert response.status_code == 200

    response = await async_client.put("/api/settings", json=response.json())
    assert response.status_code == 200

    async with SessionLocal() as session:
        settings = (await session.execute(select(DashboardSettings))).scalars().first()
        assert settings is not None
        assert settings.omniroute_sidecar_enabled is True
        assert settings.omniroute_sidecar_base_url == "http://stored-omniroute.internal:20999/v1"
        assert settings.omniroute_sidecar_api_key_encrypted == b"stored-omniroute-key"
        assert settings.omniroute_sidecar_prefixes_json == '[{"prefix": "omniroute/", "strip": false}]'
        assert settings.omniroute_sidecar_selected_models_json == f'["{OMNIROUTE_MODEL}"]'
        assert settings.omniroute_sidecar_connect_timeout_seconds == 3.25
        assert settings.omniroute_sidecar_request_timeout_seconds == 451.5
        assert settings.omniroute_sidecar_models_cache_ttl_seconds == 73.0
        assert settings.omniroute_sidecar_default_reasoning_effort == "high"


@pytest.mark.asyncio
async def test_dormant_omniroute_routes_do_not_conflict_with_orcarouter(
    async_client,
    stored_omniroute_configuration,
):
    async with SessionLocal() as session:
        settings = (await session.execute(select(DashboardSettings))).scalars().first()
        assert settings is not None
        settings.omniroute_sidecar_prefixes_json = '[{"prefix": "orcarouter/", "strip": false}]'
        await session.commit()

    response = await async_client.put(
        "/api/settings",
        json={"orcarouterSidecarModelPrefixes": [{"prefix": "orcarouter/", "strip": False}]},
    )

    assert response.status_code == 200
    assert response.json()["orcarouterSidecarModelPrefixes"] == [{"prefix": "orcarouter/", "strip": False}]

    async with SessionLocal() as session:
        settings = (await session.execute(select(DashboardSettings))).scalars().first()
        assert settings is not None
        assert settings.omniroute_sidecar_prefixes_json == '[{"prefix": "orcarouter/", "strip": false}]'


@pytest.mark.asyncio
async def test_omniroute_models_are_absent_from_model_discovery(
    lifespan_free_client,
    stored_omniroute_configuration,
    omniroute_environment_enabled,
    no_omniroute_network,
    fake_orcarouter,
):
    # ``_enable_api_key_auth`` writes settings; without the lifespan no
    # cache-invalidation poller is registered, so that write is an in-process
    # cache clear plus the temp-DB commit. It asserts its own 200 internally.
    from app.core.cache.invalidation import get_cache_invalidation_poller

    assert get_cache_invalidation_poller() is None

    await _enable_api_key_auth(lifespan_free_client)
    key = await _create_api_key("models-key")

    response = await lifespan_free_client.get("/v1/models", headers={"Authorization": f"Bearer {key.key}"})

    assert response.status_code == 200
    items = response.json()["data"]
    assert all(item["id"] != OMNIROUTE_MODEL for item in items)
    assert all(item.get("owned_by") != "omniroute" for item in items)
    # A neighbouring integration is still discoverable.
    assert any(item["id"] == ORCAROUTER_MODEL for item in items)


@pytest.mark.asyncio
async def test_omniroute_model_is_not_offered_in_the_dashboard_model_picker(
    async_client,
    stored_omniroute_configuration,
    omniroute_environment_enabled,
    no_omniroute_network,
):
    response = await async_client.get("/api/models")

    assert response.status_code == 200
    assert all(model["id"] != OMNIROUTE_MODEL for model in response.json()["models"])
    assert "omniroute" not in response.text.lower()


@pytest.mark.asyncio
async def test_chat_completions_never_route_to_omniroute(
    async_client,
    stored_omniroute_configuration,
    omniroute_environment_enabled,
    no_omniroute_network,
):
    """A stored OmniRoute model must not reach the sidecar on the chat path."""

    await _enable_api_key_auth(async_client)
    key = await _create_api_key("chat-key")

    response = await async_client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {key.key}"},
        json={"model": OMNIROUTE_MODEL, "messages": [{"role": "user", "content": "hi"}]},
    )

    # Whatever the fall-through outcome is, it must not be an OmniRoute answer.
    assert response.status_code != 200 or "omniroute" not in response.text.lower()
    async with SessionLocal() as session:
        logs = list((await session.execute(select(RequestLog))).scalars().all())
    assert [log for log in logs if log.source == "omniroute_sidecar"] == []


@pytest.mark.asyncio
async def test_responses_endpoint_never_routes_to_omniroute(
    async_client,
    stored_omniroute_configuration,
    omniroute_environment_enabled,
    no_omniroute_network,
):
    await _enable_api_key_auth(async_client)
    key = await _create_api_key("responses-key")

    response = await async_client.post(
        "/v1/responses",
        headers={"Authorization": f"Bearer {key.key}"},
        json={"model": OMNIROUTE_MODEL, "input": "hi"},
    )

    assert response.status_code != 200 or "omniroute" not in response.text.lower()
    async with SessionLocal() as session:
        logs = list((await session.execute(select(RequestLog))).scalars().all())
    assert [log for log in logs if log.source == "omniroute_sidecar"] == []


@pytest.mark.asyncio
async def test_neighbouring_orcarouter_still_dispatches_chat_requests(
    async_client,
    stored_omniroute_configuration,
    omniroute_environment_enabled,
    no_omniroute_network,
    fake_orcarouter,
):
    await _enable_api_key_auth(async_client)
    key = await _create_api_key("orca-key")

    response = await async_client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {key.key}"},
        json={"model": ORCAROUTER_MODEL, "messages": [{"role": "user", "content": "hi"}]},
    )

    assert response.status_code == 200
    assert response.json()["choices"][0]["message"]["content"] == "hi"
    assert fake_orcarouter.chat_payloads[0]["model"] == ORCAROUTER_MODEL


@pytest.mark.asyncio
async def test_omniroute_account_is_absent_from_accounts_and_dashboard(
    async_client,
    stored_omniroute_configuration,
):
    accounts = await async_client.get("/api/accounts")
    overview = await async_client.get("/api/dashboard/overview")

    assert accounts.status_code == 200
    assert overview.status_code == 200
    for response in (accounts, overview):
        assert "omniroute" not in response.text.lower()


@pytest.mark.asyncio
async def test_historical_omniroute_request_logs_are_retained(async_client, stored_omniroute_configuration):
    """Historical rows are never deleted or rewritten by the product disable."""

    from app.modules.request_logs.repository import RequestLogsRepository

    async with SessionLocal() as session:
        await RequestLogsRepository(session).add_log(
            account_id=None,
            request_id="req-historical-omniroute",
            model=OMNIROUTE_MODEL,
            input_tokens=10,
            output_tokens=5,
            cached_input_tokens=0,
            latency_ms=50,
            status="success",
            error_code=None,
            error_message=None,
            transport="http",
            api_key_id=None,
            source="omniroute_sidecar",
        )
        await session.commit()

    response = await async_client.get("/api/request-logs")
    assert response.status_code == 200

    async with SessionLocal() as session:
        stored = list((await session.execute(select(RequestLog))).scalars().all())
    historical = [log for log in stored if log.request_id == "req-historical-omniroute"]
    assert len(historical) == 1
    assert historical[0].source == "omniroute_sidecar"
    assert historical[0].model == OMNIROUTE_MODEL
