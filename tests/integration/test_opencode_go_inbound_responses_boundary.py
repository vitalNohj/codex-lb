"""What happens to a Go-prefixed model sent to ``POST /v1/responses``.

Firstmate flagged a conflict worth measuring rather than arguing about.
``contract.md`` section 4.1 says a Go model on ``/v1/responses`` "falls through
to the existing Codex Responses path exactly as today", and presents that as
preserving inbound compatibility. Those are two different claims, and only the
first one is about the code.

The concrete question an end user asks: *I configured OpenCode Go, I pointed a
Responses-protocol client at codex-lb, I asked for a Go model. What happened to
my request, and did any of my content leave for an upstream I did not choose?*

The contract's answer is that nothing special happens, which means the request
is handled by the Codex Responses path - a path whose upstream is an OpenAI
account, not OpenCode Go. So the safety-critical property is not "it works", it
is **"it must not silently succeed against the wrong provider"**. That is what
these tests pin, using the same fall-through the contract describes.

The OmniRoute precedent is directly relevant and is tested here too: OmniRoute
*is* dispatched on ``/v1/responses`` via ``_omniroute_responses_dispatch_or_none``,
and that function returns ``None`` for every other provider. So a Go provider
gets fall-through by default, and the guard that keeps it from being dispatched
to OmniRoute's upstream is a provider equality check. If a future change relaxes
that check, a Go model would be sent to OmniRoute - which is exactly the "no
automatic fallback to another paid provider" rule the captain set.

No authenticated call is made to any real provider by any test here.

SCOPE (corrected): these tests drive the **OrcaRouter** sidecar, not the native
OpenCode Go provider. They were written before the native provider existed, and
OrcaRouter is the integration pattern it was built from, so they remain valuable
as baseline regressions for the shipped providers.

Their results are evidence about OrcaRouter and **must not be cited as native Go
evidence**. The native equivalents - auth, session identity, tool calls,
streaming settlement, cancellation and no-fallback - live in
``test_opencode_go_native_chain.py``, which drives the real ``opencode_go``
dispatch path.
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
async def test_a_sidecar_model_on_v1_responses_does_not_reach_the_sidecar_upstream(
    async_client, sidecar_capability_enabled, go_upstream
):
    """The end-user-visible fact: the request does not go to the Go upstream.

    This is the reproducer for the contract's "not dispatched" claim, measured
    at the socket rather than read from source. Whatever else happens to the
    request, the configured provider's upstream sees nothing.
    """
    await _configure(async_client, go_upstream)
    client_key = await _create_key("responses-boundary-key")

    response = await async_client.post(
        "/v1/responses",
        json={"model": GO_MODEL, "input": "hello", "stream": False},
        headers={"Authorization": f"Bearer {client_key}"},
    )

    # It must not succeed, because no path can actually serve this model here.
    assert response.status_code != 200, (
        "a Responses request for a chat-only sidecar model returned success; "
        "either it was dispatched somewhere it should not have been, or an "
        "unsupported combination is being advertised as working"
    )
    # And the sidecar upstream was never contacted on any endpoint.
    assert go_upstream.requests == [], (
        f"the sidecar upstream received {[r.path for r in go_upstream.requests]} "
        "for a /v1/responses request the contract says is not dispatched to it"
    )


@pytest.mark.asyncio
async def test_a_sidecar_model_on_v1_responses_is_not_diverted_to_another_provider(
    async_client, sidecar_capability_enabled, go_upstream, monkeypatch
):
    """No automatic fallback to a different paid provider.

    ``_omniroute_responses_dispatch_or_none`` is the one sidecar branch on the
    Responses path. It is guarded by ``decision.provider != "omniroute"``. This
    test refuses the OmniRoute transport outright, so if that guard ever stops
    excluding other providers the test fails loudly instead of a Go model
    quietly billing OmniRoute.
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
    assert response.status_code != 200
    assert go_upstream.requests == []


@pytest.mark.asyncio
async def test_the_failure_is_a_clean_client_error_not_a_crash(async_client, sidecar_capability_enabled, go_upstream):
    """An unsupported combination must fail legibly.

    A 500 or a hang here is a worse end-user experience than a refusal, and it
    is what a silent fall-through into a path with no usable upstream tends to
    produce. The assertion is deliberately broad on the exact code, because the
    contract has not settled whether this becomes an explicit 400 - but it is
    strict that the response is a structured error the client can act on.
    """
    await _configure(async_client, go_upstream)
    client_key = await _create_key("responses-clean-error-key")

    response = await async_client.post(
        "/v1/responses",
        json={"model": GO_MODEL, "input": "hello", "stream": False},
        headers={"Authorization": f"Bearer {client_key}"},
    )

    assert 400 <= response.status_code < 600
    body = response.json()
    assert "error" in body, f"unstructured error body: {body}"
    assert body["error"].get("message"), "an error with no message is not actionable"
    # The upstream credential must not leak through an error path either.
    assert UPSTREAM_KEY not in response.text


@pytest.mark.asyncio
async def test_the_existing_responses_path_still_works_for_a_non_sidecar_model(
    async_client, sidecar_capability_enabled, go_upstream
):
    """Inbound Responses compatibility is preserved for everything else.

    The contract's compatibility claim rests on *not* registering a new branch.
    This pins the other half: enabling a sidecar integration must not change how
    an ordinary Responses request is handled. It fails for want of a configured
    OpenAI upstream, which is the pre-existing behavior in this test
    environment - the point is that it fails the same way, and not inside the
    sidecar.
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
    """Do not advertise a protocol the integration cannot serve.

    The contract is explicit that ``/v1/models`` should carry
    ``api_types: ["chat_completions"]`` for Go models. The binding rule, tested
    here against the current baseline, is the negative one: a chat-only sidecar
    model must never be listed as Responses-capable, or a client will choose the
    endpoint the tests above prove does not work.
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
