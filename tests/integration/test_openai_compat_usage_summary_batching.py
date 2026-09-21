"""Per-source request-usage aggregation for the generic OpenAI-compat endpoints.

Reported on https://github.com/vitalNohj/codex-lb/pull/59: listing accounts (and
the dashboard overview) issued one request-log aggregate per configured endpoint.
That was a fixed handful for the named sidecars, but this feature lets an operator
configure up to ``OPENAI_COMPAT_MAX_ENDPOINTS`` of them, turning a page load into
an N+1 over an aggregate query.

Batching an accounting query is only safe if it returns the *same numbers*, so
these tests pin equivalence with the per-source form first, then pin that the
batched form is actually one query.
"""

from __future__ import annotations

import pytest
from sqlalchemy import event

from app.db.session import SessionLocal
from app.modules.accounts.repository import AccountsRepository
from app.modules.request_logs.repository import RequestLogsRepository

pytestmark = pytest.mark.integration

_SOURCE_A = "openai_compat:2c9b8f3a-1e4d-4b7a-9c11-7a0e4d2b1c0a"
_SOURCE_B = "openai_compat:3d0c9e4b-2f5e-4c8b-8d22-8b1f5e3c2d1b"
_SOURCE_UNUSED = "openai_compat:4e1daf5c-3061-4d9c-9e33-9c2f6f4d3e2c"


async def _seed_logs() -> None:
    """Two endpoints with different usage, plus rows that must be excluded."""

    async with SessionLocal() as session:
        repo = RequestLogsRepository(session)
        await repo.add_log(
            account_id=None,
            request_id="req-a1",
            model="Qwen/Qwen2.5-7B",
            input_tokens=100,
            output_tokens=20,
            cached_input_tokens=10,
            latency_ms=5,
            status="success",
            error_code=None,
            source=_SOURCE_A,
            cost_usd=0.5,
        )
        await repo.add_log(
            account_id=None,
            request_id="req-a2",
            model="Qwen/Qwen2.5-7B",
            input_tokens=50,
            output_tokens=5,
            cached_input_tokens=0,
            latency_ms=5,
            status="error",
            error_code="boom",
            source=_SOURCE_A,
            cost_usd=0.25,
        )
        await repo.add_log(
            account_id=None,
            request_id="req-b1",
            model="meta/llama-3.1-8b",
            input_tokens=7,
            output_tokens=3,
            cached_input_tokens=None,
            latency_ms=5,
            status="success",
            error_code=None,
            source=_SOURCE_B,
            cost_usd=None,
        )
        # A different integration entirely: must not bleed into either answer.
        await repo.add_log(
            account_id=None,
            request_id="req-other",
            model="deepseek/deepseek-chat",
            input_tokens=9_999,
            output_tokens=9_999,
            cached_input_tokens=None,
            latency_ms=5,
            status="success",
            error_code=None,
            source="openrouter_sidecar",
            cost_usd=42.0,
        )
        # Warmup traffic is excluded from these totals by the existing filter.
        await repo.add_log(
            account_id=None,
            request_id="req-warmup",
            model="Qwen/Qwen2.5-7B",
            input_tokens=1_000,
            output_tokens=1_000,
            cached_input_tokens=None,
            latency_ms=5,
            status="success",
            error_code=None,
            source=_SOURCE_A,
            request_kind="warmup",
        )
        await session.commit()


@pytest.mark.asyncio
async def test_the_batched_form_returns_exactly_what_the_per_source_form_returns(db_setup):
    """Equivalence first: an accounting query may only be batched if it agrees.

    Same filters, same exclusions, same rounding - only the grouping changes.
    """

    await _seed_logs()

    async with SessionLocal() as session:
        repo = AccountsRepository(session)
        per_source = {
            source: await repo.request_usage_summary_for_source(source)
            for source in (_SOURCE_A, _SOURCE_B, _SOURCE_UNUSED)
        }
        batched = await repo.request_usage_summaries_for_sources([_SOURCE_A, _SOURCE_B, _SOURCE_UNUSED])

    assert batched[_SOURCE_A] == per_source[_SOURCE_A]
    assert batched[_SOURCE_B] == per_source[_SOURCE_B]
    # Both rows and both endpoints, with the other integration and the warmup row
    # excluded - so the grouping really is per-source and the filters still apply.
    assert per_source[_SOURCE_A].request_count == 2
    assert per_source[_SOURCE_A].total_tokens == 175
    assert per_source[_SOURCE_A].cached_input_tokens == 10
    assert per_source[_SOURCE_A].total_cost_usd == 0.75
    assert per_source[_SOURCE_B].request_count == 1
    assert per_source[_SOURCE_B].total_tokens == 10


@pytest.mark.asyncio
async def test_a_source_with_no_rows_reads_as_an_empty_summary(db_setup):
    """A freshly added endpoint has no logs, and must read as zeros, not raise.

    The grouped query omits empty sources rather than emitting a zero row, so the
    single-source wrapper substitutes the empty summary. Both are pinned because
    the callers rely on each.
    """

    await _seed_logs()

    async with SessionLocal() as session:
        repo = AccountsRepository(session)
        empty = await repo.request_usage_summary_for_source(_SOURCE_UNUSED)
        batched = await repo.request_usage_summaries_for_sources([_SOURCE_UNUSED])

    assert empty.request_count == 0
    assert empty.total_tokens == 0
    assert empty.total_cost_usd == 0.0
    assert _SOURCE_UNUSED not in batched


@pytest.mark.asyncio
async def test_many_endpoints_cost_one_query_not_one_each(db_setup):
    """The actual N+1 claim, counted rather than asserted by inspection.

    Counts real emitted SELECT statements: the per-source loop scales with the
    endpoint count, the batched call does not.
    """

    await _seed_logs()
    sources = [f"openai_compat:0000000{index}-0000-4000-8000-000000000001" for index in range(8)]

    async with SessionLocal() as session:
        repo = AccountsRepository(session)
        engine = session.get_bind()

        selects: list[str] = []

        def _record(_conn, _cursor, statement, _params, _context, _executemany):
            if statement.lstrip().upper().startswith("SELECT"):
                selects.append(statement)

        event.listen(engine, "before_cursor_execute", _record)
        try:
            selects.clear()
            await repo.request_usage_summaries_for_sources(sources)
            batched_queries = len(selects)

            selects.clear()
            for source in sources:
                await repo.request_usage_summary_for_source(source)
            serial_queries = len(selects)
        finally:
            event.remove(engine, "before_cursor_execute", _record)

    assert batched_queries == 1, f"expected one grouped aggregate, saw {batched_queries}"
    assert serial_queries == len(sources), f"expected one query per source, saw {serial_queries}"


@pytest.mark.asyncio
async def test_listing_accounts_does_not_scale_its_queries_with_the_endpoint_count(db_setup, async_client):
    """End to end through the accounts API, which is where the N+1 was observed.

    Configuring a second endpoint must not add a second usage aggregate. Counted
    on the real endpoint rather than on the repository, so the wiring is covered
    too and not just the helper.
    """

    from app.db.session import engine as app_engine

    endpoint = {
        "name": "Vast",
        "id": "2c9b8f3a-1e4d-4b7a-9c11-7a0e4d2b1c0a",
        "enabled": True,
        "baseUrl": "https://openai.vast.ai/demo/v1",
        "modelPrefixes": [],
        "fullModels": ["Qwen/Qwen2.5-7B"],
        "connectTimeoutSeconds": 8,
        "requestTimeoutSeconds": 600,
        "modelsCacheTtlSeconds": 60,
    }
    second = {
        **endpoint,
        "id": "3d0c9e4b-2f5e-4c8b-8d22-8b1f5e3c2d1b",
        "name": "vLLM",
        "baseUrl": "https://vllm.internal/v1",
        "fullModels": ["meta/llama-3.1-8b"],
    }

    usage_selects: list[str] = []

    def _record(_conn, _cursor, statement, _params, _context, _executemany):
        # The per-source aggregate is the only SELECT that filters on
        # ``request_logs.source``, so match on that rather than counting
        # everything the accounts page reads.
        collapsed = " ".join(statement.split()).lower()
        if collapsed.startswith("select") and "request_logs.source" in collapsed:
            usage_selects.append(collapsed)

    for endpoints in ([endpoint], [endpoint, second]):
        response = await async_client.put("/api/settings", json={"openaiCompatEndpoints": endpoints})
        assert response.status_code == 200, response.text

        event.listen(app_engine.sync_engine, "before_cursor_execute", _record)
        try:
            usage_selects.clear()
            accounts = await async_client.get("/api/accounts")
            assert accounts.status_code == 200, accounts.text
            counts = len(usage_selects)
        finally:
            event.remove(app_engine.sync_engine, "before_cursor_execute", _record)

        if len(endpoints) == 1:
            one_endpoint_queries = counts
        else:
            two_endpoint_queries = counts

    # One extra endpoint must not buy one extra aggregate.
    assert two_endpoint_queries == one_endpoint_queries, (
        f"usage queries scaled with the endpoint count: {one_endpoint_queries} -> {two_endpoint_queries}"
    )
