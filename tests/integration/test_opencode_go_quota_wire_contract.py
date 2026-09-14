"""The quota endpoint's wire shape, checked against what the Accounts card reads.

The backend serves `GET /api/opencode-go/quota` and the Accounts card parses it
with a zod schema in `frontend/src/features/accounts/opencode-go-schemas.ts`.
Each side has thorough tests of its own, and both pass - but each tests against
its *own* idea of the payload. Nothing currently fails if the two drift apart,
which is exactly the class of defect this lane already found twice on this
feature (`supported` vs `routable`, and `protocol: "unknown"` rejected by a zod
enum).

So this asserts the seam directly: the **real** backend response, produced by a
real HTTP request through the mounted route against a fake upstream, is checked
field-by-field against the literal expectations the **real** frontend schema
declares. It reads the frontend file as data rather than importing TypeScript,
so it runs in the Python suite with no extra toolchain.

Deliberately *not* a duplicate of `test_opencode_go_quota_reachability.py`: that
proves the route serves the chain at all. This proves the bytes it serves are
the bytes the card can consume.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import pytest_asyncio

from app.core.config.settings import get_settings
from tests.fixtures.opencode_go_upstream import FakeOpenCodeGoUpstream

pytestmark = pytest.mark.integration

QUOTA_PATH = "/api/opencode-go/quota"
UPSTREAM_KEY = "sk-go-wire-Zq7SvT2pLm9KdR4xHn8B"

REPO_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_SCHEMA = REPO_ROOT / "frontend/src/features/accounts/opencode-go-schemas.ts"


@pytest.fixture
def opencode_go_enabled(monkeypatch):
    monkeypatch.setenv("CODEX_LB_OPENCODE_GO_SIDECAR_ENABLED", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest_asyncio.fixture
async def go_upstream(monkeypatch):
    upstream = FakeOpenCodeGoUpstream(
        api_key=UPSTREAM_KEY,
        model_ids=("glm-5.3",),
        strict_auth_by_endpoint=False,
    )
    await upstream.start()

    import app.modules.opencode_go.service as quota_service
    from app.core.clients.opencode_go import OpenCodeGoClient

    class _Redirected(OpenCodeGoClient):
        @property
        def base_url(self) -> str:
            return upstream.base_url

    monkeypatch.setattr(quota_service, "OpenCodeGoClient", _Redirected, raising=False)
    quota_service.reset_opencode_go_quota_cache()
    try:
        yield upstream
    finally:
        quota_service.reset_opencode_go_quota_cache()
        await upstream.stop()


async def _configure(client) -> None:
    response = await client.put(
        "/api/settings",
        json={
            "opencodeGoSidecarEnabled": True,
            "opencodeGoSidecarBaseUrl": "https://opencode.ai/zen/go/v1",
            "opencodeGoSidecarApiKey": UPSTREAM_KEY,
        },
    )
    assert response.status_code == 200, response.text


def _schema_source() -> str:
    if not FRONTEND_SCHEMA.exists():
        pytest.skip(f"frontend schema not present: {FRONTEND_SCHEMA}")
    return FRONTEND_SCHEMA.read_text()


def _declared_literals(source: str, schema_name: str) -> set[str]:
    """Extract the string members of a named ``z.enum([...])`` declaration."""
    match = re.search(rf"{schema_name}\s*=\s*z\.enum\(\[(.*?)\]\)", source, re.DOTALL)
    assert match, f"{schema_name} not found in the frontend schema"
    return set(re.findall(r'"([^"]+)"', match.group(1)))


@pytest.mark.asyncio
async def test_every_field_the_card_requires_is_present_in_the_real_response(
    async_client, opencode_go_enabled, go_upstream
):
    """The card's required keys must all appear in the served payload.

    A missing key is the failure that produced an always-"not configured" card
    earlier in this feature's history, so it is asserted against the real
    response rather than a fixture either lane wrote.
    """
    await _configure(async_client)

    response = await async_client.get(QUOTA_PATH)
    assert response.status_code == 200, response.text
    body = response.json()

    # Declared by the card's own schema; camelCase over the wire.
    required = {
        "status",
        "scope",
        "message",
        "checkedAt",
        "refreshedAt",
        "stale",
        "staleReason",
        "modelBreakdownAvailable",
        "models",
        "windows",
    }
    missing = required - set(body)
    assert not missing, f"the served quota payload is missing keys the card reads: {sorted(missing)}"

    window = body["windows"][0]
    required_window = {"key", "upstreamKey", "status", "percentUsed", "resetsAt", "limitReached"}
    missing_window = required_window - set(window)
    assert not missing_window, f"window object missing keys the card reads: {sorted(missing_window)}"


@pytest.mark.asyncio
async def test_the_served_status_and_scope_are_values_the_card_accepts(async_client, opencode_go_enabled, go_upstream):
    """Every literal the backend can emit must be in the card's enums.

    This is the exact shape of the earlier `protocol: "unknown"` defect, where a
    value the backend genuinely sends was absent from a zod enum and rejected
    the whole payload. Checked here for the quota surface across the full set of
    statuses the backend can produce, not only the happy one.
    """
    source = _schema_source()
    accepted_status = _declared_literals(source, "OpenCodeGoQuotaStatusSchema")
    accepted_scope = _declared_literals(source, "OpenCodeGoQuotaScopeSchema")
    accepted_window_status = _declared_literals(source, "OpenCodeGoQuotaWindowStatusSchema")
    accepted_window_key = _declared_literals(source, "OpenCodeGoQuotaWindowKeySchema")

    served: set[str] = set()

    # 1. Unconfigured, before any settings write.
    first = await async_client.get(QUOTA_PATH)
    assert first.status_code == 200
    served.add(first.json()["status"])

    # 2. Configured and served from the upstream.
    await _configure(async_client)
    ok = await async_client.get(QUOTA_PATH)
    assert ok.status_code == 200
    ok_body = ok.json()
    served.add(ok_body["status"])

    assert ok_body["scope"] in accepted_scope, (
        f"served scope {ok_body['scope']!r} is not in the card's enum {sorted(accepted_scope)}"
    )
    for window in ok_body["windows"]:
        assert window["status"] in accepted_window_status, (
            f"served window status {window['status']!r} not in {sorted(accepted_window_status)}"
        )
        assert window["key"] in accepted_window_key, (
            f"served window key {window['key']!r} not in {sorted(accepted_window_key)}"
        )

    # 3. Upstream rejects the credential.
    import app.modules.opencode_go.service as quota_service

    quota_service.reset_opencode_go_quota_cache()
    go_upstream.script("/v1/usage", status=401, repeat=None)
    unauthorized = await async_client.get(QUOTA_PATH)
    assert unauthorized.status_code == 200
    served.add(unauthorized.json()["status"])

    unrepresentable = served - accepted_status
    assert not unrepresentable, (
        f"the backend served quota statuses the card's schema rejects: {sorted(unrepresentable)}. "
        f"served={sorted(served)} accepted={sorted(accepted_status)}. A zod enum "
        "rejects an unlisted string, so the whole card payload would fail to parse."
    )


@pytest.mark.asyncio
async def test_a_no_data_status_carries_an_empty_window_list_on_the_wire(
    async_client, opencode_go_enabled, go_upstream
):
    """The rule that keeps a failed fetch from rendering as an exhausted plan.

    Asserted on the serialized bytes, because that is what the card parses -
    a service-level unit test cannot catch a serializer that emits ``null``
    where the card expects ``[]``.
    """
    import app.modules.opencode_go.service as quota_service

    await _configure(async_client)
    quota_service.reset_opencode_go_quota_cache()
    go_upstream.script("/v1/usage", status=401, repeat=None)

    response = await async_client.get(QUOTA_PATH)
    assert response.status_code == 200
    raw = response.text
    body = response.json()

    assert body["status"] != "ok"
    assert body["windows"] == [], "a no-data status carried windows"
    assert body["models"] == []
    assert body["modelBreakdownAvailable"] is False
    # Not null, and not omitted: the card reads these as arrays.
    assert '"windows":[]' in raw.replace(" ", "")
    assert UPSTREAM_KEY not in raw


@pytest.mark.asyncio
async def test_percent_used_is_served_without_a_derived_remaining_field(async_client, opencode_go_enabled, go_upstream):
    """Direction is single-source evidence; a derived inverse must not appear.

    Emitting ``percentRemaining`` would give a one-source directional inference
    the appearance of a second confirmation, which the quota contract forbids.
    """
    await _configure(async_client)

    response = await async_client.get(QUOTA_PATH)
    assert response.status_code == 200
    body = response.json()

    for window in body["windows"]:
        assert "percentUsed" in window
        assert "percentRemaining" not in window, (
            "the wire payload carries a derived percentRemaining; the used "
            "direction is a single-source inference and must not be dressed up "
            "as a second confirmation"
        )

    five_hour = next(window for window in body["windows"] if window["key"] == "five_hour")
    assert five_hour["percentUsed"] == 42
    # The verbatim upstream key survives, so a future live capture is diffable.
    assert five_hour["upstreamKey"] == "rolling"


@pytest.mark.asyncio
async def test_the_payload_is_json_serializable_exactly_as_the_card_will_parse_it(
    async_client, opencode_go_enabled, go_upstream
):
    """Round-trip the served bytes, so nothing depends on FastAPI's test client."""
    await _configure(async_client)

    response = await async_client.get(QUOTA_PATH)
    assert response.status_code == 200
    reparsed = json.loads(response.content.decode("utf-8"))

    assert reparsed == response.json()
    assert isinstance(reparsed["windows"], list)
    assert isinstance(reparsed["stale"], bool)
    assert reparsed["checkedAt"] is None or isinstance(reparsed["checkedAt"], str)
