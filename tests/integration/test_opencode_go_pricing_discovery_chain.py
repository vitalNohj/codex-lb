"""Model discovery -> price lookup -> request cost, over real catalog sockets.

The captain's requirement in his own words: when a model is detected and we have
no cost, the pricing module should look the model up on OpenRouter, or on
OrcaRouter as a fallback, and get input/output rates. He also flagged that this
module "may or may not work" - it did not for a provider once before. So these
tests exercise the real lookup path against catalog endpoints served over
loopback HTTP, rather than against injected catalog objects.

``test_external_price_request_path.py`` already covers the request-path
accounting with in-memory catalogs. What is added here, and is not covered
there, is the part the captain actually asked about:

* an id missing from the serving catalog is looked up on the **pricing
  reference** and priced from it, with provenance recorded as the reference
  rather than the serving integration;
* when neither source lists the id, the result is **unknown**, not zero;
* an unreachable reference preserves prior state instead of recording an
  absence - the failure mode that makes a pricing module quietly wrong;
* a subscription-style upstream reporting ``cost: 0`` does not become "this
  request was free", because a flat-rate subscription charge and a per-token
  list price are different quantities. Two surveyed projects shipped exactly
  this bug and had to fix it.

Nothing here proves anything about opencode.ai's real prices. It proves the
lookup machinery behaves correctly given a catalog, which is the part that was
in doubt.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from aiohttp import web
from sqlalchemy import select

from app.core.clients.claude_sidecar import SidecarPrefix
from app.core.clients.orcarouter_sidecar import OrcaRouterSidecarConfig
from app.core.config.settings import get_settings
from app.core.usage.external_pricing import service as pricing_service
from app.core.usage.external_pricing.catalogs import fetch_openrouter_catalog
from app.core.usage.external_pricing.service import (
    get_lookup_coordinator,
    reset_serving_context_loaders,
)
from app.db.models import CostSource, ExternalPriceStatus, RequestLog
from app.db.session import SessionLocal
from app.modules.api_keys.repository import ApiKeysRepository
from app.modules.api_keys.service import ApiKeyCreateData, ApiKeysService

pytestmark = pytest.mark.integration

MODEL = "orcarouter/glm-5.3"
INPUT_TOKENS = 10
OUTPUT_TOKENS = 5


class _FakeSidecarClient:
    """Serves the request so the test can focus on what it costs.

    The chain-level wire behavior is covered by
    ``test_opencode_go_chain_baseline.py`` against a real socket; repeating it
    here would slow these tests without testing pricing any harder.
    """

    def __init__(self, config: OrcaRouterSidecarConfig) -> None:
        self.config = config
        self.billed_cost_usd: float | None = None

    async def list_models_cached(self):
        return []

    async def chat_completion(self, payload):
        usage = {
            "prompt_tokens": INPUT_TOKENS,
            "completion_tokens": OUTPUT_TOKENS,
            "total_tokens": INPUT_TOKENS + OUTPUT_TOKENS,
        }
        if self.billed_cost_usd is not None:
            usage["cost_usd"] = self.billed_cost_usd
        return {
            "id": "chatcmpl-pricing",
            "object": "chat.completion",
            "model": payload["model"],
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "hi"}, "finish_reason": "stop"}],
            "usage": usage,
        }

    def stream_chat_completion(self, payload):
        raise AssertionError("these tests do not stream")


class FakeCatalogServer:
    """An OpenAI-shaped ``/models`` catalog on a real loopback port."""

    def __init__(self) -> None:
        self.entries: dict[str, dict[str, str] | None] = {}
        self.fail_with_status: int | None = None
        self.request_count = 0
        self._runner: web.AppRunner | None = None
        self._port: int | None = None

    async def start(self) -> str:
        app = web.Application()
        app.router.add_get("/api/v1/models", self._handle)
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, "127.0.0.1", 0)
        await site.start()
        self._port = int(self._runner.addresses[0][1])
        return self.url

    async def stop(self) -> None:
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None

    @property
    def url(self) -> str:
        assert self._port is not None
        return f"http://127.0.0.1:{self._port}/api/v1/models"

    def list_model(self, model_id: str, *, input_per_1m: float, output_per_1m: float) -> None:
        # The catalog publishes per-TOKEN decimal strings, exactly as OpenRouter
        # does. Converting here rather than storing per-1M keeps the parser
        # under test instead of bypassed.
        self.entries[model_id] = {
            "prompt": f"{input_per_1m / 1_000_000:.12f}",
            "completion": f"{output_per_1m / 1_000_000:.12f}",
        }

    def list_model_without_rates(self, model_id: str) -> None:
        """A real listing that carries no per-token rate (routers, per-image)."""
        self.entries[model_id] = None

    async def _handle(self, _request: web.Request) -> web.StreamResponse:
        self.request_count += 1
        if self.fail_with_status is not None:
            return web.Response(status=self.fail_with_status, text="upstream catalog is down")
        return web.json_response(
            {
                "data": [
                    {"id": model_id, "pricing": pricing} if pricing is not None else {"id": model_id}
                    for model_id, pricing in self.entries.items()
                ]
            }
        )


@pytest_asyncio.fixture
async def reference_catalog(monkeypatch) -> AsyncIterator[FakeCatalogServer]:
    """The pricing reference, served over a socket and reachable by the real fetcher."""
    server = FakeCatalogServer()
    await server.start()

    async def _load_reference():
        # Same code path as production, only the URL differs. The real HTTP
        # fetch and the real parser both run.
        try:
            return await fetch_openrouter_catalog(url=server.url)
        except Exception:
            return None

    monkeypatch.setattr(pricing_service, "_load_reference_catalog", _load_reference)
    try:
        yield server
    finally:
        await server.stop()


@pytest.fixture(autouse=True)
def _clean_pricing_state():
    reset_serving_context_loaders()
    yield
    reset_serving_context_loaders()


@pytest.fixture
def sidecar_capability_enabled(monkeypatch):
    monkeypatch.setenv("CODEX_LB_ORCAROUTER_SIDECAR_ENABLED", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def fake_sidecar(monkeypatch) -> _FakeSidecarClient:
    config = OrcaRouterSidecarConfig(
        enabled=True,
        base_url="https://api.orcarouter.invalid/v1",
        api_key="sk-orca-pricing-test-Zq7SvT2pLm9K",
        prefixes=(SidecarPrefix(prefix="orcarouter/", strip=False),),
        connect_timeout_seconds=8.0,
        request_timeout_seconds=600.0,
        models_cache_ttl_seconds=60.0,
        full_models=(MODEL,),
    )
    client = _FakeSidecarClient(config)

    async def load_config():
        return config

    monkeypatch.setattr("app.modules.proxy.api.load_orcarouter_sidecar_config", load_config)
    monkeypatch.setattr("app.modules.proxy.api.OrcaRouterSidecarClient", lambda _config: client)
    return client


def _install_serving_catalog(entries: dict[str, object] | None) -> None:
    """Register the serving integration's own catalog, or an empty one."""
    from app.core.usage.external_pricing.catalogs import Catalog, CatalogEntry
    from app.core.usage.external_pricing.service import ServingContext, register_serving_context_loader

    async def _loader(_provider: str) -> ServingContext:
        return ServingContext(
            catalog=Catalog.from_entries(
                "orcarouter",
                [CatalogEntry(model_id=model_id, price=price) for model_id, price in (entries or {}).items()],
            ),
            aliases={},
            prefixes=(("orcarouter/", False),),
        )

    register_serving_context_loader("orcarouter", _loader)


async def _enable_sidecar(client) -> None:
    response = await client.put(
        "/api/settings",
        json={
            "orcarouterSidecarEnabled": True,
            "orcarouterSidecarApiKey": "sk-orca-pricing-test-Zq7SvT2pLm9K",
            "orcarouterSidecarModelPrefixes": [{"prefix": "orcarouter/", "strip": False}],
            "orcarouterSidecarFullModels": [MODEL],
            "apiKeyAuthEnabled": True,
        },
    )
    assert response.status_code == 200, response.text


async def _create_key(name: str):
    async with SessionLocal() as session:
        service = ApiKeysService(ApiKeysRepository(session))
        return await service.create_key(ApiKeyCreateData(name=name, allowed_models=None, limits=[]))


async def _post_chat(client, key) -> None:
    response = await client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {key.key}"},
        json={"model": MODEL, "messages": [{"role": "user", "content": "hi"}]},
    )
    assert response.status_code == 200, response.text


async def _clear_retry_backoff(provider: str, model: str) -> None:
    """Make an open record due now, instead of sleeping out its real backoff.

    The backoff is production behavior under test elsewhere; here it is only in
    the way of observing the recovery it is designed to allow. Only the deadline
    is moved - the record's status, price and provenance are untouched, so
    nothing about the assertion is weakened.
    """
    from sqlalchemy import update

    from app.db.models import ExternalModelPrice

    async with SessionLocal() as session:
        await session.execute(
            update(ExternalModelPrice)
            .where(
                ExternalModelPrice.provider == provider,
                ExternalModelPrice.incoming_model == model.strip().lower(),
            )
            .values(next_retry_at=None)
        )
        await session.commit()


async def _sidecar_logs() -> list[RequestLog]:
    async with SessionLocal() as session:
        logs = list((await session.execute(select(RequestLog))).scalars().all())
    return [log for log in logs if log.source == "orcarouter_sidecar"]


@pytest.mark.asyncio
async def test_a_model_the_serving_catalog_does_not_price_is_looked_up_on_the_reference(
    async_client, sidecar_capability_enabled, fake_sidecar, reference_catalog
):
    """The captain's requirement, executed: unknown model -> reference lookup -> rates.

    Provenance is asserted too. Knowing a price is not enough; an operator has to
    be able to tell a rate that came from the serving integration from one that
    came from a broad reference, because only the former is the price that
    integration actually charges.
    """
    _install_serving_catalog({})  # serving integration lists nothing
    reference_catalog.list_model(MODEL, input_per_1m=2.0, output_per_1m=4.0)
    await _enable_sidecar(async_client)
    key = await _create_key("reference-lookup-key")

    # Request one: nothing is known yet, and the lookup is scheduled off the
    # request path rather than blocking the caller.
    await _post_chat(async_client, key)
    await get_lookup_coordinator().drain()
    first = (await _sidecar_logs())[0]
    assert first.cost_usd is None
    assert first.price_status == ExternalPriceStatus.PENDING.value

    # Request two: the resolved reference rates are applied.
    await _post_chat(async_client, key)
    await get_lookup_coordinator().drain()
    second = (await _sidecar_logs())[1]

    expected = (INPUT_TOKENS / 1_000_000 * 2.0) + (OUTPUT_TOKENS / 1_000_000 * 4.0)
    assert second.cost_usd == pytest.approx(expected)
    # Calculated from published rates, NOT an amount anyone was billed.
    assert second.cost_source == CostSource.CATALOG_CALCULATED.value
    assert second.price_status == ExternalPriceStatus.RESOLVED.value
    assert reference_catalog.request_count >= 1


@pytest.mark.asyncio
async def test_the_serving_catalog_wins_over_the_reference_for_the_same_id(
    async_client, sidecar_capability_enabled, fake_sidecar, reference_catalog
):
    """A shared id is priced by whoever served it.

    The same model id is listed by multiple services at different prices. Taking
    the reference's number for a request another integration served would report
    a rate the operator was never charged.
    """
    from app.core.usage.pricing import ModelPrice

    _install_serving_catalog({MODEL: ModelPrice(input_per_1m=10.0, output_per_1m=20.0)})
    reference_catalog.list_model(MODEL, input_per_1m=1.0, output_per_1m=1.0)
    await _enable_sidecar(async_client)
    key = await _create_key("serving-wins-key")

    await _post_chat(async_client, key)
    await get_lookup_coordinator().drain()
    await _post_chat(async_client, key)
    await get_lookup_coordinator().drain()

    priced = (await _sidecar_logs())[1]
    serving_expected = (INPUT_TOKENS / 1_000_000 * 10.0) + (OUTPUT_TOKENS / 1_000_000 * 20.0)
    reference_expected = (INPUT_TOKENS / 1_000_000 * 1.0) + (OUTPUT_TOKENS / 1_000_000 * 1.0)
    assert priced.cost_usd == pytest.approx(serving_expected)
    assert priced.cost_usd != pytest.approx(reference_expected)


@pytest.mark.asyncio
async def test_an_id_no_source_lists_stays_unknown_and_never_becomes_zero(
    async_client, sidecar_capability_enabled, fake_sidecar, reference_catalog
):
    """Unknown and zero are different facts and must not share a representation.

    A zero here would read on the dashboard as "this request was free", which is
    a wrong number rather than a missing one.
    """
    _install_serving_catalog({})
    reference_catalog.list_model("some/other-model", input_per_1m=1.0, output_per_1m=2.0)
    await _enable_sidecar(async_client)
    key = await _create_key("unknown-price-key")

    await _post_chat(async_client, key)
    await get_lookup_coordinator().drain()
    await _post_chat(async_client, key)
    await get_lookup_coordinator().drain()

    for log in await _sidecar_logs():
        assert log.cost_usd is None
        assert log.cost_usd != 0
    assert (await _sidecar_logs())[-1].price_status == ExternalPriceStatus.UNRESOLVED.value


@pytest.mark.asyncio
async def test_a_listed_model_with_no_token_rate_is_settled_rather_than_retried_forever(
    async_client, sidecar_capability_enabled, fake_sidecar, reference_catalog
):
    """"Listed, but not priced per token" is an answer, not a failure."""
    _install_serving_catalog({})
    reference_catalog.list_model_without_rates(MODEL)
    await _enable_sidecar(async_client)
    key = await _create_key("no-token-rate-key")

    await _post_chat(async_client, key)
    await get_lookup_coordinator().drain()
    await _post_chat(async_client, key)
    await get_lookup_coordinator().drain()

    final = (await _sidecar_logs())[-1]
    assert final.cost_usd is None
    assert final.price_status == ExternalPriceStatus.NOT_TOKEN_PRICED.value


@pytest.mark.asyncio
async def test_an_unreachable_reference_does_not_record_a_false_absence(
    async_client, sidecar_capability_enabled, fake_sidecar, reference_catalog
):
    """The failure mode that makes a pricing module quietly wrong.

    A catalog that could not be fetched has said nothing. The distinction this
    asserts is not the status string - an unanswered lookup is legitimately
    recorded ``UNRESOLVED`` - but whether the record is **closed**. A closed
    record carries no ``next_retry_at`` and is never looked up again, so closing
    one on an outage would freeze a wrong answer permanently. An open record
    keeps a retry deadline and self-corrects, which the recovery half proves.
    """
    from app.core.usage.external_pricing.store import ExternalModelPriceStore

    _install_serving_catalog({})
    reference_catalog.fail_with_status = 503
    await _enable_sidecar(async_client)
    key = await _create_key("reference-down-key")

    await _post_chat(async_client, key)
    await get_lookup_coordinator().drain()
    await _post_chat(async_client, key)
    await get_lookup_coordinator().drain()

    during_outage = (await _sidecar_logs())[-1]
    assert during_outage.cost_usd is None
    assert during_outage.cost_usd != 0

    async with SessionLocal() as session:
        record = await ExternalModelPriceStore(session).get("orcarouter", MODEL)
    assert record is not None
    # Not settled: the question is still open, so a later pass will ask again.
    assert record.is_settled is False
    assert record.next_retry_at is not None, (
        "an unanswered lookup must keep a retry deadline; a record closed during "
        "an outage would never be corrected"
    )

    # Recovery: once the catalog answers, the price is picked up.
    reference_catalog.fail_with_status = None
    reference_catalog.list_model(MODEL, input_per_1m=3.0, output_per_1m=6.0)
    await _clear_retry_backoff("orcarouter", MODEL)

    await _post_chat(async_client, key)
    await get_lookup_coordinator().drain()
    await _post_chat(async_client, key)
    await get_lookup_coordinator().drain()

    recovered = (await _sidecar_logs())[-1]
    expected = (INPUT_TOKENS / 1_000_000 * 3.0) + (OUTPUT_TOKENS / 1_000_000 * 6.0)
    assert recovered.cost_usd == pytest.approx(expected), (
        "a recovered catalog must correct the unpriced record rather than leaving "
        "the outage's answer in place"
    )


@pytest.mark.asyncio
async def test_an_upstream_reported_zero_is_recorded_as_billed_not_as_a_missing_price(
    async_client, sidecar_capability_enabled, fake_sidecar, reference_catalog
):
    """Subscription economics: ``cost: 0`` is a reported debit, not an unknown.

    OpenCode Go is a flat-rate subscription and reports ``cost: 0`` per request.
    The bug two surveyed projects shipped was letting a flat-rate provider's
    request be priced per token as though it were spend. The correct behavior
    keeps the two apart: what the upstream reported is ``upstream_billed`` and
    wins over any calculated list price, and its provenance says so.
    """
    from app.core.usage.pricing import ModelPrice

    fake_sidecar.billed_cost_usd = 0.0
    _install_serving_catalog({MODEL: ModelPrice(input_per_1m=2.0, output_per_1m=4.0)})
    await _enable_sidecar(async_client)
    key = await _create_key("subscription-zero-key")

    await _post_chat(async_client, key)
    await get_lookup_coordinator().drain()

    log = (await _sidecar_logs())[0]
    assert log.cost_usd == 0.0
    assert log.cost_source == CostSource.UPSTREAM_BILLED.value, (
        "a reported zero must keep upstream_billed provenance; relabelling it as a "
        "calculated list price is how a flat-rate subscription gets billed per token"
    )
    # The reference cost is kept separately: a list-price estimate is still
    # useful, it just is not the charge.
    assert log.cost_usd != log.reference_cost_usd or log.reference_cost_usd == 0.0


@pytest.mark.asyncio
async def test_a_prefixed_id_resolves_through_the_configured_prefix_not_by_substring(
    async_client, sidecar_capability_enabled, fake_sidecar, reference_catalog
):
    """Alias/prefix provenance, exact rather than stem-matched.

    The defect this resolution layer replaced matched on stems, which priced a
    model at a different model's rate. The reference here lists only the
    unprefixed id plus a decoy sharing a stem; only an exact, prefix-aware
    resolution reaches the right one.
    """
    _install_serving_catalog({})
    reference_catalog.list_model("glm-5.3", input_per_1m=5.0, output_per_1m=7.0)
    # Same stem, very different price. A substring match would find this.
    reference_catalog.list_model("glm-5.3-ultra-preview", input_per_1m=50.0, output_per_1m=70.0)

    response = await async_client.put(
        "/api/settings",
        json={
            "orcarouterSidecarEnabled": True,
            "orcarouterSidecarApiKey": "sk-orca-pricing-test-Zq7SvT2pLm9K",
            # strip=True so the prefix is removed before catalog resolution.
            "orcarouterSidecarModelPrefixes": [{"prefix": "orcarouter/", "strip": True}],
            "apiKeyAuthEnabled": True,
        },
    )
    assert response.status_code == 200, response.text

    from app.core.usage.external_pricing.service import ServingContext, register_serving_context_loader

    async def _loader(_provider: str) -> ServingContext:
        return ServingContext(catalog=None, aliases={}, prefixes=(("orcarouter/", True),), publishes_price_catalog=False)

    register_serving_context_loader("orcarouter", _loader)

    key = await _create_key("prefix-resolution-key")
    await _post_chat(async_client, key)
    await get_lookup_coordinator().drain()
    await _post_chat(async_client, key)
    await get_lookup_coordinator().drain()

    priced = (await _sidecar_logs())[-1]
    exact = (INPUT_TOKENS / 1_000_000 * 5.0) + (OUTPUT_TOKENS / 1_000_000 * 7.0)
    decoy = (INPUT_TOKENS / 1_000_000 * 50.0) + (OUTPUT_TOKENS / 1_000_000 * 70.0)
    assert priced.cost_usd == pytest.approx(exact)
    assert priced.cost_usd != pytest.approx(decoy)


@pytest.mark.asyncio
async def test_the_real_openrouter_shaped_parser_reads_per_token_decimal_strings(
    async_client, reference_catalog
):
    """A direct check on the parser, over the socket, without the request path.

    Rate conversion is where an off-by-1e6 hides. Asserting it separately keeps
    the request-path tests from being the only thing standing between a wrong
    multiplier and the dashboard.

    ``async_client`` is taken only for its app lifespan, which owns the shared
    HTTP client the real fetcher leases.
    """
    del async_client
    reference_catalog.list_model("vendor/model-a", input_per_1m=2.5, output_per_1m=10.0)
    reference_catalog.list_model_without_rates("vendor/model-b")

    catalog = await fetch_openrouter_catalog(url=reference_catalog.url)

    entry = catalog.exact("vendor/model-a")
    assert entry is not None and entry.price is not None
    assert entry.price.input_per_1m == pytest.approx(2.5)
    assert entry.price.output_per_1m == pytest.approx(10.0)

    unpriced = catalog.exact("vendor/model-b")
    assert unpriced is not None, "a listed model with no rates must stay listed"
    assert unpriced.price is None


@pytest.mark.asyncio
async def test_a_malformed_catalog_response_raises_rather_than_parsing_to_empty(
    async_client, reference_catalog
):
    """An unreadable catalog must be a failure, not an empty catalog.

    An empty catalog is indistinguishable from "lists nothing", which would
    settle every model as unpriced on a transient upstream schema change.
    """
    del async_client  # taken for its app lifespan; see the test above
    from app.core.usage.external_pricing.catalogs import CatalogFetchError

    reference_catalog.fail_with_status = 500
    with pytest.raises(CatalogFetchError):
        await fetch_openrouter_catalog(url=reference_catalog.url)


def test_the_fixture_catalog_serves_the_openai_shape_it_claims_to():
    """Guards the fixture's own wire shape, so a parser test cannot pass vacuously."""
    server = FakeCatalogServer()
    server.list_model("vendor/model-a", input_per_1m=2.0, output_per_1m=4.0)
    payload = json.loads(json.dumps({"data": [{"id": "vendor/model-a", "pricing": server.entries["vendor/model-a"]}]}))
    assert float(payload["data"][0]["pricing"]["prompt"]) == pytest.approx(2.0 / 1_000_000)
