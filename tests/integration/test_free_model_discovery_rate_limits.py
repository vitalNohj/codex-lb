"""Discovery behaviour under provider rate limiting.

Grown from the reproduction that diagnosed a run the operator reported as
"failed on the first one then stopped". The run had not stopped: it was
backing off after a 429 while the dashboard reported ``0 resolved`` with no
explanation, and the give-up path silently dropped its final probe.

Everything below the transport is real - API, runner, repository, settings
session, provider_access, error classifier and the serialization boundary -
and only the outbound socket is mocked. **No live provider calls.**

The load-bearing property across these cases is CONSERVATISM about scope: a
rejection is treated as provider-wide only when the vendor explicitly said so.
Several tests exist specifically to prove the code does NOT over-claim, because
parking a healthy provider would skip candidates that would have passed.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.core.crypto import TokenEncryptor
from app.core.utils.time import utcnow
from app.db.models import DashboardSettings, FreeModelDiscoveryRunItem
from app.db.session import SessionLocal
from app.modules.free_model_discovery import runner as runner_module
from app.modules.free_model_discovery.repository import FreeModelDiscoveryRepository
from app.modules.free_model_discovery.runner import FreeModelDiscoveryRunner

pytestmark = pytest.mark.integration

# Synthetic, never a real credential.
_FAKE_OPENROUTER_KEY = "sk-test-openrouter-0123456789"


class _FakeResponse:
    def __init__(self, status: int, text: str, headers: Mapping[str, str] | None = None) -> None:
        self.status = status
        self._text = text
        self.headers = dict(headers or {})

    async def __aenter__(self) -> "_FakeResponse":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def text(self) -> str:
        return self._text


class _ScriptedHttpSession:
    """Scripted responses per model id; the last entry repeats."""

    def __init__(self, script: Mapping[str, list[tuple[int, str, dict[str, str]]]]) -> None:
        self._script = {k: list(v) for k, v in script.items()}
        self.posted: list[str] = []

    def post(self, url: str, *, headers, json, timeout) -> _FakeResponse:
        del url, headers, timeout
        model_id = str(json["model"])
        self.posted.append(model_id)
        queue = self._script.get(model_id)
        if not queue:
            raise AssertionError(f"unscripted probe for {model_id}")
        status, body, hdrs = queue[0] if len(queue) == 1 else queue.pop(0)
        return _FakeResponse(status, body, hdrs)


class _FakeLease:
    def __init__(self, session: _ScriptedHttpSession) -> None:
        self._session = session

    async def __aenter__(self) -> _ScriptedHttpSession:
        return self._session

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


async def _stop(task: "asyncio.Task[None]") -> None:
    """Stop a driver we started mid-run.

    The driver may legitimately have finished already - a run whose queue
    drained needs no cancelling - so a missing ``CancelledError`` is not a
    failure. Anything else it raised is still surfaced.
    """

    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


def _ok() -> tuple[int, str, dict[str, str]]:
    return (200, json.dumps({"choices": [{"message": {"role": "assistant", "content": "ok"}}]}), {})


def _empty_200() -> tuple[int, str, dict[str, str]]:
    return (200, json.dumps({"choices": [{"message": {"role": "assistant", "content": ""}}]}), {})


def _upstream_429() -> tuple[int, str, dict[str, str]]:
    """OpenRouter's UPSTREAM-provider 429 - the shape seen in production.

    Documented to carry ``error.metadata.provider_code``/``provider_name`` and
    no ``X-RateLimit-*`` family.
    https://openrouter.ai/docs/api_reference/limits
    """

    return (
        429,
        json.dumps(
            {
                "error": {
                    "code": 429,
                    "message": "Provider returned error",
                    "metadata": {"is_byok": False, "provider_name": "SomeUpstream", "provider_code": 429},
                }
            }
        ),
        {},
    )


def _ambiguous_429() -> tuple[int, str, dict[str, str]]:
    """A 429 with no scope evidence at all. Must stay ``unknown``."""

    return (429, json.dumps({"error": {"code": 429, "message": "Provider returned error"}}), {})


def _platform_429(retry_after: str = "3600") -> tuple[int, str, dict[str, str]]:
    """OpenRouter's OWN platform limit: explicit account/free-tier-wide scope."""

    return (
        429,
        json.dumps(
            {
                "error": {
                    "code": 429,
                    "message": "Rate limit exceeded",
                    "metadata": {"error_type": "rate_limit_exceeded"},
                }
            }
        ),
        {
            "X-RateLimit-Limit": "50",
            "X-RateLimit-Remaining": "0",
            "X-RateLimit-Reset": "1789000000000",
            "Retry-After": retry_after,
        },
    )


def _credits_402() -> tuple[int, str, dict[str, str]]:
    return (402, json.dumps({"error": {"code": 402, "message": "Insufficient credits"}}), {})


@pytest.fixture
def scripted(monkeypatch):
    def _install(script):
        http = _ScriptedHttpSession(script)
        monkeypatch.setattr(
            "app.core.clients.openrouter_sidecar.lease_http_session", lambda: _FakeLease(http)
        )
        return http

    monkeypatch.setattr(runner_module, "_WAIT_SLICE_SECONDS", 0.001)
    monkeypatch.setattr(runner_module, "_INCONCLUSIVE_REQUEUE", timedelta(seconds=0))
    return _install


async def _enable_openrouter() -> None:
    async with SessionLocal() as session:
        settings = (await session.execute(select(DashboardSettings))).scalar_one()
        settings.openrouter_sidecar_enabled = True
        settings.openrouter_sidecar_api_key_encrypted = TokenEncryptor().encrypt(_FAKE_OPENROUTER_KEY)
        settings.orcarouter_sidecar_enabled = False
        settings.orcarouter_sidecar_api_key_encrypted = None
        await session.commit()


async def _create_run(
    model_ids: list[str], *, max_attempts: int = 12, hours: int = 24, floor: float = 0.001, cap: float = 0.004
) -> str:
    now = utcnow()
    async with SessionLocal() as session:
        run = await FreeModelDiscoveryRepository(session).create_run(
            started_at=now,
            deadline_at=now + timedelta(hours=hours),
            pacing_floor_seconds=floor,
            pacing_cap_seconds=cap,
            max_attempts_per_item=max_attempts,
            items=[("openrouter", m, "new") for m in model_ids],
        )
        return run.id


async def _items() -> list[FreeModelDiscoveryRunItem]:
    async with SessionLocal() as session:
        return list((await session.execute(select(FreeModelDiscoveryRunItem))).scalars().all())


# --- success control -------------------------------------------------------


@pytest.mark.asyncio
async def test_clean_probes_complete_the_run(async_client, scripted):
    """The proven path stays intact: clean 200s resolve and the run completes."""

    scripted({"m/a:free": [_ok()], "m/b:free": [_empty_200()]})
    await _enable_openrouter()
    run_id = await _create_run(["m/a:free", "m/b:free"])

    await FreeModelDiscoveryRunner(enabled=True).drive_run(run_id)

    body = (await async_client.get(f"/api/free-model-discovery/runs/{run_id}")).json()
    assert body["status"] == "completed"
    assert body["counts"]["passed"] == 1
    assert body["counts"]["failed"] == 1
    assert body["counts"]["queued"] == 0
    # A clean verdict carries no rate-limit attribution.
    assert {item["limitScope"] for item in body["items"]} == {None}


# --- attempt accounting ----------------------------------------------------


@pytest.mark.asyncio
async def test_every_issued_probe_is_counted_exactly_once(async_client, scripted):
    """The give-up transition follows a real request, so it must be counted.

    Regression: ``mark_unresolved`` did not increment ``attempts``, so the
    column sat one below the probes actually sent and contradicted its own
    "gave up after N attempts" text.
    """

    del async_client
    http = scripted({"m/a:free": [_upstream_429()]})
    await _enable_openrouter()
    run_id = await _create_run(["m/a:free"], max_attempts=4)

    await FreeModelDiscoveryRunner(enabled=True).drive_run(run_id)

    items = await _items()
    assert len(http.posted) == 4, "four requests were really issued"
    assert items[0].attempts == 4, "and all four are counted"
    assert items[0].state == "unresolved"
    assert "gave up after 4 attempts" in (items[0].last_outcome or "")


@pytest.mark.asyncio
async def test_a_parked_provider_consumes_no_attempts(async_client, scripted):
    """No request issued means no attempt spent: these models are untested,
    not tried and rejected."""

    del async_client
    http = scripted({})
    async with SessionLocal() as session:
        settings = (await session.execute(select(DashboardSettings))).scalar_one()
        settings.openrouter_sidecar_enabled = False
        settings.openrouter_sidecar_api_key_encrypted = None
        await session.commit()
    run_id = await _create_run(["m/a:free"])

    await FreeModelDiscoveryRunner(enabled=True).drive_run(run_id)

    items = await _items()
    assert http.posted == []
    assert items[0].attempts == 0
    assert items[0].state == "unresolved"


# --- scope: the conservative core -----------------------------------------


@pytest.mark.asyncio
async def test_an_ambiguous_429_never_claims_a_provider_wide_limit(async_client, scripted):
    """A bare 429 with a generic message proves nothing about scope, and must
    not pause the provider or mark untried models unavailable."""

    http = scripted({"m/a:free": [_ambiguous_429()], "m/b:free": [_ok()]})
    await _enable_openrouter()
    run_id = await _create_run(["m/a:free", "m/b:free"], max_attempts=2)

    await FreeModelDiscoveryRunner(enabled=True).drive_run(run_id)

    body = (await async_client.get(f"/api/free-model-discovery/runs/{run_id}")).json()
    by_id = {item["modelId"]: item for item in body["items"]}
    assert by_id["m/a:free"]["limitScope"] == "unknown"
    # The other model was still probed and resolved on its own merits.
    assert by_id["m/b:free"]["state"] == "passed"
    assert "m/b:free" in http.posted


@pytest.mark.asyncio
async def test_an_upstream_attributed_429_is_model_scoped(async_client, scripted):
    """``provider_name``/``provider_code`` name an upstream backend, so the
    limit belongs to that model's route - not to the account."""

    http = scripted({"m/a:free": [_upstream_429()], "m/b:free": [_ok()]})
    await _enable_openrouter()
    run_id = await _create_run(["m/a:free", "m/b:free"], max_attempts=2)

    await FreeModelDiscoveryRunner(enabled=True).drive_run(run_id)

    body = (await async_client.get(f"/api/free-model-discovery/runs/{run_id}")).json()
    by_id = {item["modelId"]: item for item in body["items"]}
    assert by_id["m/a:free"]["limitScope"] == "model"
    assert by_id["m/b:free"]["state"] == "passed"
    assert http.posted.count("m/b:free") == 1


@pytest.mark.asyncio
async def test_mixed_success_and_rejection_never_declares_the_account_exhausted(async_client, scripted):
    """The production shape. Interleaved 200s and 429s must leave every
    rejection's scope unproven and keep discovering."""

    scripted(
        {
            "m/limited:free": [_ambiguous_429()],
            "m/ok:free": [_ok()],
            "m/also-ok:free": [_ok()],
        }
    )
    await _enable_openrouter()
    run_id = await _create_run(["m/limited:free", "m/ok:free", "m/also-ok:free"], max_attempts=2)

    await FreeModelDiscoveryRunner(enabled=True).drive_run(run_id)

    body = (await async_client.get(f"/api/free-model-discovery/runs/{run_id}")).json()
    assert body["counts"]["passed"] == 2, "successes still land while another model is limited"
    by_id = {item["modelId"]: item for item in body["items"]}
    assert by_id["m/limited:free"]["limitScope"] == "unknown"
    assert all(not provider["providerPaused"] for provider in body["providers"])


# --- explicit shared limit -------------------------------------------------


@pytest.mark.asyncio
async def test_an_explicit_shared_limit_pauses_the_whole_group_once(async_client, scripted):
    """When the vendor names its OWN platform limit, waiting once at the group
    level beats trying every remaining item through the same known block."""

    http = scripted(
        {
            "m/a:free": [_platform_429(retry_after="1")],
            "m/b:free": [_ok()],
            "m/c:free": [_ok()],
        }
    )
    await _enable_openrouter()
    run_id = await _create_run(["m/a:free", "m/b:free", "m/c:free"], max_attempts=3)

    task = asyncio.create_task(FreeModelDiscoveryRunner(enabled=True).drive_run(run_id))
    await asyncio.sleep(0.15)

    # The remaining queue was deferred rather than each item spending an
    # attempt discovering the same provider-wide block.
    async with SessionLocal() as session:
        queued = (
            await session.execute(
                select(FreeModelDiscoveryRunItem).where(FreeModelDiscoveryRunItem.state == "queued")
            )
        ).scalars().all()
    assert all(item.next_attempt_at is not None for item in queued)
    assert http.posted.count("m/b:free") == 0, "untried models were not pushed through the block"

    await _stop(task)


@pytest.mark.asyncio
async def test_a_shared_limit_surfaces_a_truthful_waiting_reason(async_client, scripted):
    """The operator must see why discovery is waiting, with the scope named."""

    scripted({"m/a:free": [_platform_429(retry_after="600")], "m/b:free": [_ok()]})
    await _enable_openrouter()
    run_id = await _create_run(["m/a:free", "m/b:free"], max_attempts=3)

    task = asyncio.create_task(FreeModelDiscoveryRunner(enabled=True).drive_run(run_id))
    await asyncio.sleep(0.15)
    body = (await async_client.get(f"/api/free-model-discovery/runs/{run_id}")).json()
    await _stop(task)

    provider = body["providers"][0]
    assert provider["providerPaused"] is True
    assert provider["limitScope"] == "shared"
    assert "Provider-wide limit reached" in (provider["waitingReason"] or "")
    # A real published wait is reported; no countdown is invented.
    assert "10m" in (provider["waitingReason"] or "")


@pytest.mark.asyncio
async def test_a_vendor_wait_longer_than_the_pacing_cap_is_not_shortened(async_client, scripted):
    """A heuristic cap bounds only the heuristic. Retrying earlier than the
    provider instructed is what earns a harder throttle."""

    del async_client
    scripted({"m/a:free": [_platform_429(retry_after="1800")]})
    await _enable_openrouter()
    # Pacing cap far below the vendor's stated wait.
    run_id = await _create_run(["m/a:free"], max_attempts=3, floor=0.001, cap=0.004)

    before = utcnow()
    task = asyncio.create_task(FreeModelDiscoveryRunner(enabled=True).drive_run(run_id))
    await asyncio.sleep(0.15)
    await _stop(task)

    items = await _items()
    assert items[0].next_attempt_at is not None
    # Deferred far beyond the 0.004s cap, honouring the 1800s instruction.
    assert (items[0].next_attempt_at - before).total_seconds() > 60


@pytest.mark.asyncio
async def test_cancellation_interrupts_a_long_provider_wait(async_client, scripted):
    """A provider-wide wait must not sleep through cancel or the deadline."""

    del async_client
    scripted({"m/a:free": [_platform_429(retry_after="3600")], "m/b:free": [_ok()]})
    await _enable_openrouter()
    run_id = await _create_run(["m/a:free", "m/b:free"], max_attempts=3)

    task = asyncio.create_task(FreeModelDiscoveryRunner(enabled=True).drive_run(run_id))
    await asyncio.sleep(0.1)
    async with SessionLocal() as session:
        await FreeModelDiscoveryRepository(session).request_cancel(run_id)

    # Returns promptly rather than waiting out the hour.
    await asyncio.wait_for(task, timeout=5.0)


@pytest.mark.asyncio
async def test_a_deferred_wait_survives_a_restart(async_client, scripted):
    """The group wait is persisted, so a process restart mid-window cannot
    accidentally bypass a limit the vendor imposed."""

    del async_client
    scripted({"m/a:free": [_platform_429(retry_after="1800")], "m/b:free": [_ok()]})
    await _enable_openrouter()
    run_id = await _create_run(["m/a:free", "m/b:free"], max_attempts=3)

    task = asyncio.create_task(FreeModelDiscoveryRunner(enabled=True).drive_run(run_id))
    await asyncio.sleep(0.15)
    await _stop(task)

    # A fresh runner reads the persisted deferral, not in-memory state.
    async with SessionLocal() as session:
        item = await FreeModelDiscoveryRepository(session).next_queued_item(run_id, "openrouter")
    assert item is not None
    assert item.next_attempt_at is not None
    assert item.next_attempt_at > utcnow()


# --- 402 -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_402_is_recorded_without_claiming_permanent_failure(async_client, scripted):
    """A credit error is not proven permanent - a per-key cap can reset - so
    it must not be labelled a dead account or a broken model."""

    scripted({"m/a:free": [_credits_402()]})
    await _enable_openrouter()
    run_id = await _create_run(["m/a:free"], max_attempts=2)

    await FreeModelDiscoveryRunner(enabled=True).drive_run(run_id)

    body = (await async_client.get(f"/api/free-model-discovery/runs/{run_id}")).json()
    item = body["items"][0]
    assert item["state"] == "unresolved", "unresolved, never 'failed' - the model was not judged"
    assert item["lastHttpStatus"] == 402
    # No scope claim from a bare 402.
    assert item["limitScope"] is None
    assert body["errorMessage"] is None


# --- evidence hygiene ------------------------------------------------------


@pytest.mark.asyncio
async def test_no_credential_or_arbitrary_vendor_text_reaches_run_state(async_client, scripted):
    """Only whitelisted retry/limit fields cross the boundary."""

    scripted(
        {
            "m/a:free": [
                (
                    429,
                    json.dumps(
                        {
                            "error": {
                                "code": 429,
                                "message": f"upstream echoed Bearer {_FAKE_OPENROUTER_KEY}",
                                "metadata": {"error_type": "rate_limit_exceeded", "raw": "sk-leaked-secret"},
                            }
                        }
                    ),
                    {"Retry-After": "1", "Set-Cookie": "session=abc", "X-Account-Id": "acct_999"},
                )
            ]
        }
    )
    await _enable_openrouter()
    run_id = await _create_run(["m/a:free"], max_attempts=2)

    await FreeModelDiscoveryRunner(enabled=True).drive_run(run_id)

    serialized = json.dumps((await async_client.get(f"/api/free-model-discovery/runs/{run_id}")).json())
    assert _FAKE_OPENROUTER_KEY not in serialized
    assert "sk-leaked-secret" not in serialized
    assert "acct_999" not in serialized
    assert "session=abc" not in serialized


@pytest.mark.asyncio
async def test_counts_split_never_attempted_from_retrying(async_client, scripted):
    """The symptom that started this: a retrying run read as untouched."""

    scripted({"m/a:free": [_ambiguous_429()], "m/b:free": [_ok()]})
    await _enable_openrouter()
    run_id = await _create_run(["m/a:free", "m/b:free"], max_attempts=6)

    task = asyncio.create_task(FreeModelDiscoveryRunner(enabled=True).drive_run(run_id))
    await asyncio.sleep(0.1)
    body = (await async_client.get(f"/api/free-model-discovery/runs/{run_id}")).json()
    await _stop(task)

    counts = body["counts"]
    assert counts["retrying"] + counts["awaitingFirstAttempt"] == counts["queued"]
    assert counts["retrying"] >= 1, "a probed-and-requeued item is not 'never attempted'"


# --- review findings F1/F2 -------------------------------------------------


def _upstream_429_with_retry_after(seconds: str = "3600") -> tuple[int, str, dict[str, str]]:
    """Model-scoped rejection that ALSO publishes a long wait."""

    return (
        429,
        json.dumps(
            {
                "error": {
                    "code": 429,
                    "message": "Provider returned error",
                    "metadata": {"provider_name": "SomeUpstream", "provider_code": 429},
                }
            }
        ),
        {"Retry-After": seconds},
    )


def _shared_limit_in_200_body() -> tuple[int, str, dict[str, str]]:
    """OpenRouter documents a provider failure after headers were sent as a
    200 whose body holds only an error object."""

    return (
        200,
        json.dumps({"error": {"code": 429, "metadata": {"error_type": "rate_limit_exceeded"}}}),
        {},
    )


@pytest.mark.asyncio
async def test_a_model_scoped_wait_does_not_stall_other_models(async_client, scripted):
    """F1: a long Retry-After on a MODEL-scoped rejection must park that item,
    not sleep the whole provider queue.

    Honouring it provider-wide would block models that would have passed - the
    opposite of what this change is for - so the wait is bounded by the pacing
    cap for the loop while the offending item carries the real delay.
    """

    http = scripted(
        {
            "m/limited:free": [_upstream_429_with_retry_after("3600")],
            "m/ok:free": [_ok()],
            "m/also-ok:free": [_ok()],
        }
    )
    await _enable_openrouter()
    run_id = await _create_run(["m/limited:free", "m/ok:free", "m/also-ok:free"], max_attempts=3)

    # The run legitimately stays open - the limited item is parked an hour out
    # and that wait is honoured - so drive it concurrently and assert that the
    # OTHER models were probed promptly rather than sleeping behind it.
    task = asyncio.create_task(FreeModelDiscoveryRunner(enabled=True).drive_run(run_id))
    body: dict = {}
    for _ in range(400):
        await asyncio.sleep(0.02)
        body = (await async_client.get(f"/api/free-model-discovery/runs/{run_id}")).json()
        if body["counts"]["passed"] == 2:
            break
    await _stop(task)

    assert body["counts"]["passed"] == 2, "other models were probed, not stalled behind one model's wait"
    assert http.posted.count("m/ok:free") == 1
    assert http.posted.count("m/also-ok:free") == 1
    # The offending item carries the vendor wait itself.
    by_id = {item["modelId"]: item for item in body["items"]}
    assert by_id["m/limited:free"]["limitScope"] == "model"
    # And the provider was never presented as paused for a model-scoped limit.
    assert all(not provider["providerPaused"] for provider in body["providers"])


@pytest.mark.asyncio
async def test_a_model_scoped_wait_parks_the_offending_item_until_it_elapses(async_client, scripted):
    """F1, other half: the vendor's wait is still respected for that item."""

    del async_client
    scripted({"m/limited:free": [_upstream_429_with_retry_after("3600")], "m/ok:free": [_ok()]})
    await _enable_openrouter()
    run_id = await _create_run(["m/limited:free", "m/ok:free"], max_attempts=3)

    before = utcnow()
    task = asyncio.create_task(FreeModelDiscoveryRunner(enabled=True).drive_run(run_id))
    for _ in range(300):
        await asyncio.sleep(0.02)
        async with SessionLocal() as session:
            probed = (
                await session.execute(
                    select(FreeModelDiscoveryRunItem).where(
                        FreeModelDiscoveryRunItem.model_id == "m/limited:free"
                    )
                )
            ).scalar_one()
            if probed.attempts > 0:
                break
    await _stop(task)

    async with SessionLocal() as session:
        item = (
            await session.execute(
                select(FreeModelDiscoveryRunItem).where(
                    FreeModelDiscoveryRunItem.model_id == "m/limited:free"
                )
            )
        ).scalar_one()
    assert item.attempts == 1
    assert item.state == "queued"
    assert item.next_attempt_at is not None
    # Parked roughly an hour out, not the 2-minute default requeue.
    assert (item.next_attempt_at - before).total_seconds() > 600


@pytest.mark.asyncio
async def test_scope_from_a_200_error_body_is_persisted(async_client, scripted):
    """F2: the documented 200-with-error case sets a scope and can pause the
    group, so that scope must be durable - otherwise a restart or a second
    replica loses the only explanation for the pause."""

    scripted({"m/a:free": [_shared_limit_in_200_body()], "m/b:free": [_ok()]})
    await _enable_openrouter()
    run_id = await _create_run(["m/a:free", "m/b:free"], max_attempts=2)

    task = asyncio.create_task(FreeModelDiscoveryRunner(enabled=True).drive_run(run_id))
    await asyncio.sleep(0.15)
    await _stop(task)

    async with SessionLocal() as session:
        item = (
            await session.execute(
                select(FreeModelDiscoveryRunItem).where(FreeModelDiscoveryRunItem.model_id == "m/a:free")
            )
        ).scalar_one()
    assert item.last_http_status == 200
    assert item.last_limit_scope == "shared", "scope must persist even without a 429 status"

    # And it survives into the API without the in-memory runner state.
    body = (await async_client.get(f"/api/free-model-discovery/runs/{run_id}")).json()
    by_id = {i["modelId"]: i for i in body["items"]}
    assert by_id["m/a:free"]["limitScope"] == "shared"


@pytest.mark.asyncio
async def test_a_model_scoped_wait_does_not_move_the_shared_pacer(async_client, scripted):
    """A model-scoped limit must not slow down unrelated models.

    ``_apply_result`` used to call ``pacer.on_rate_limited()`` before checking
    scope, so one model's ``Retry-After: 3600`` drove the SHARED provider pacer
    straight to its 600s cap. The offending item was already parked, yet every
    later model then waited ten minutes between probes, and the pacer only
    decays after three clean responses.

    Uses PRODUCTION pacing values deliberately: with a test cap of a few
    milliseconds the defect is arithmetically invisible.
    """

    del async_client
    scripted(
        {
            "m/limited:free": [_upstream_429_with_retry_after("3600")],
            "m/ok:free": [_ok()],
        }
    )
    await _enable_openrouter()
    run_id = await _create_run(
        ["m/limited:free", "m/ok:free"], max_attempts=3, floor=20.0, cap=600.0
    )

    captured: list[float] = []
    original = FreeModelDiscoveryRunner._apply_result

    async def _record(self, session, repository, item, result, pacer, max_attempts):
        wait = await original(self, session, repository, item, result, pacer, max_attempts)
        captured.append(pacer.current_seconds)
        return wait

    runner = FreeModelDiscoveryRunner(enabled=True)
    FreeModelDiscoveryRunner._apply_result = _record  # type: ignore[method-assign]
    try:
        task = asyncio.create_task(runner.drive_run(run_id))
        for _ in range(200):
            await asyncio.sleep(0.02)
            if captured:
                break
        await _stop(task)
    finally:
        FreeModelDiscoveryRunner._apply_result = original  # type: ignore[method-assign]

    assert captured, "the limited item should have been probed"
    # The shared pacer stays at the floor: this rejection was one model's, and
    # the vendor's wait is carried by that item's own next_attempt_at.
    assert captured[0] == 20.0, (
        f"model-scoped limit moved the shared pacer to {captured[0]}s, "
        "delaying every unrelated model"
    )
