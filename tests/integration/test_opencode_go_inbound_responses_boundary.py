"""What happens to an OrcaRouter model sent to ``POST /v1/responses``.

Chat already routes this provider. Responses uses that same route: the request
is translated into a chat completion and sent to the OrcaRouter upstream, not
to a ChatGPT Codex account and not to a different sidecar. OmniRoute and native
OpenCode Go keep their own Responses dispatchers; this file does not cover them.

No authenticated call is made to any real provider by any test here.

SCOPE: these tests drive the **OrcaRouter** sidecar, not the native OpenCode Go
provider. They were written before the native provider existed. Their results
are evidence about OrcaRouter and **must not be cited as native Go evidence**.
The native equivalents live in ``test_opencode_go_native_chain.py``.
"""

from __future__ import annotations

import pytest
import pytest_asyncio

from app.core.config.settings import get_settings
from app.db.session import SessionLocal
from app.modules.api_keys.repository import ApiKeysRepository
from app.modules.api_keys.service import ApiKeyCreateData, ApiKeysService
from tests.fixtures.opencode_go_upstream import FakeOpenCodeGoUpstream

pytestmark = pytest.mark.integration

UPSTREAM_KEY = "sk-orca-go-resp-Zq7SvT2pLm9KdR4xHn8B"
PREFIX = "orcarouter/"
GO_MODEL = f"{PREFIX}glm-5.3"


@pytest.fixture
def sidecar_capability_enabled(monkeypatch):
    monkeypatch.setenv("CODEX_LB_ORCAROUTER_SIDECAR_ENABLED", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest_asyncio.fixture
async def go_upstream():
    upstream = FakeOpenCodeGoUpstream(
        api_key=UPSTREAM_KEY,
        model_ids=(GO_MODEL,),
        strict_auth_by_endpoint=False,
    )
    await upstream.start()
    try:
        yield upstream
    finally:
        await upstream.stop()


async def _configure(client, upstream: FakeOpenCodeGoUpstream, *, advertise: bool = False) -> None:
    body = {
        "orcarouterSidecarEnabled": True,
        "orcarouterSidecarBaseUrl": upstream.base_url,
        "orcarouterSidecarApiKey": UPSTREAM_KEY,
        "orcarouterSidecarModelPrefixes": [{"prefix": PREFIX, "strip": False}],
        "apiKeyAuthEnabled": True,
    }
    if advertise:
        # Full models are what put an id into ``GET /v1/models``. Without this
        # the advertisement test would skip and prove nothing.
        body["orcarouterSidecarFullModels"] = [GO_MODEL]
    response = await client.put("/api/settings", json=body)
    assert response.status_code == 200, response.text


async def _create_key(name: str) -> str:
    async with SessionLocal() as session:
        service = ApiKeysService(ApiKeysRepository(session))
        created = await service.create_key(ApiKeyCreateData(name=name, allowed_models=None, limits=[]))
    return created.key


@pytest.mark.asyncio
async def test_a_sidecar_model_on_v1_responses_reaches_that_providers_chat_upstream(
    async_client, sidecar_capability_enabled, go_upstream
):
    """Responses for an OrcaRouter model is that provider's chat completion.

    The client speaks Responses. The upstream speaks chat. The translated
    request must arrive on this provider's chat endpoint, and the client must
    get a Responses result back.
    """
    await _configure(async_client, go_upstream)
    client_key = await _create_key("responses-boundary-key")

    response = await async_client.post(
        "/v1/responses",
        json={"model": GO_MODEL, "input": "hello", "stream": False},
        headers={"Authorization": f"Bearer {client_key}"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["object"] == "response"
    assert [record.path for record in go_upstream.requests] == ["/v1/chat/completions"]
    assert go_upstream.requests[0].body["model"] == GO_MODEL


@pytest.mark.asyncio
async def test_a_sidecar_model_on_v1_responses_is_not_diverted_to_another_provider(
    async_client, sidecar_capability_enabled, go_upstream, monkeypatch
):
    """An OrcaRouter Responses request stays on OrcaRouter.

    OmniRoute has its own Responses dispatcher. This refuses that transport, so
    a routing mistake that hands the model to OmniRoute fails here instead of
    billing the wrong provider.
    """
    import app.modules.proxy.api as proxy_api

    diverted: list[str] = []

    def _refuse_omniroute(*args, **kwargs):
        del args, kwargs
        diverted.append("omniroute")
        raise AssertionError("a sidecar model was dispatched to the OmniRoute upstream from /v1/responses")

    monkeypatch.setattr(proxy_api, "OmniRouteSidecarClient", _refuse_omniroute, raising=True)
    monkeypatch.setattr(proxy_api, "proxy_responses_to_omniroute", _refuse_omniroute, raising=True)

    await _configure(async_client, go_upstream)
    client_key = await _create_key("responses-no-divert-key")

    response = await async_client.post(
        "/v1/responses",
        json={"model": GO_MODEL, "input": "hello", "stream": False},
        headers={"Authorization": f"Bearer {client_key}"},
    )

    assert diverted == []
    assert response.status_code == 200, response.text
    assert [record.path for record in go_upstream.requests] == ["/v1/chat/completions"]


@pytest.mark.asyncio
async def test_the_responses_result_does_not_leak_the_upstream_credential(
    async_client, sidecar_capability_enabled, go_upstream
):
    """A successful translation must not echo the provider credential."""
    await _configure(async_client, go_upstream)
    client_key = await _create_key("responses-clean-error-key")

    response = await async_client.post(
        "/v1/responses",
        json={"model": GO_MODEL, "input": "hello", "stream": False},
        headers={"Authorization": f"Bearer {client_key}"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["object"] == "response"
    assert UPSTREAM_KEY not in response.text


@pytest.mark.asyncio
async def test_the_existing_responses_path_still_works_for_a_non_sidecar_model(
    async_client, sidecar_capability_enabled, go_upstream
):
    """Inbound Responses compatibility is preserved for everything else.

    Enabling OrcaRouter must not change how an ordinary Codex Responses request
    is handled. It fails for want of a configured OpenAI upstream, which is the
    pre-existing behavior in this test environment - the point is that it fails
    the same way, and not inside the sidecar.
    """
    await _configure(async_client, go_upstream)
    client_key = await _create_key("responses-passthrough-key")

    response = await async_client.post(
        "/v1/responses",
        json={"model": "gpt-5.4", "input": "hello", "stream": False},
        headers={"Authorization": f"Bearer {client_key}"},
    )

    assert response.status_code != 200
    assert go_upstream.requests == []


@pytest.mark.asyncio
async def test_v1_models_does_not_advertise_responses_support_for_a_chat_only_model(
    async_client, sidecar_capability_enabled, go_upstream
):
    """Keep the catalog's api_types shape.

    Responses traffic for this model is translated onto chat. The catalog still
    names ``chat_completions`` and does not add a native ``responses`` type.
    """
    await _configure(async_client, go_upstream, advertise=True)
    client_key = await _create_key("models-advertisement-key")

    response = await async_client.get("/v1/models", headers={"Authorization": f"Bearer {client_key}"})
    assert response.status_code == 200

    entries = {entry["id"]: entry for entry in response.json()["data"]}
    listed = entries.get(GO_MODEL)
    assert listed is not None, (
        f"{GO_MODEL} was configured as a full model but is not advertised in "
        f"/v1/models; advertised ids were {sorted(entries)}"
    )

    api_types = listed.get("api_types")
    assert api_types is not None, (
        "the advertised model carries no api_types, so a client cannot tell which endpoint to use and will guess"
    )
    assert "responses" not in api_types, (
        f"{GO_MODEL} is advertised as Responses-capable but a Responses request for it does not reach the provider"
    )
    assert "chat_completions" in api_types
