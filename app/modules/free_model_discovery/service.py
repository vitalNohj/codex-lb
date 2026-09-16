from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import cast

from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clients.openrouter_sidecar import (
    OpenRouterSidecarClient,
    OpenRouterSidecarError,
    OpenRouterSidecarUnavailableError,
)
from app.core.clients.orcarouter_sidecar import (
    OrcaRouterSidecarError,
    OrcaRouterSidecarUnavailableError,
    get_orcarouter_sidecar_client,
)
from app.core.config.settings_cache import get_settings_cache
from app.core.exceptions import (
    DashboardBadRequestError,
    DashboardConflictError,
    DashboardNotFoundError,
    DashboardSettingsConflictError,
)
from app.core.utils.time import utcnow
from app.db.models import DashboardSettings, FreeModelDiscoveryRun, FreeModelDiscoveryRunItem
from app.modules.free_model_discovery.candidates import (
    build_candidates,
    normalize_model_key,
    split_candidates,
)
from app.modules.free_model_discovery.pacing import (
    DEFAULT_MAX_ATTEMPTS_PER_ITEM,
    DEFAULT_PACING_CAP_SECONDS,
    DEFAULT_PACING_FLOOR_SECONDS,
    DEFAULT_RUN_WALL_CLOCK,
)
from app.modules.free_model_discovery.probe import SidecarProbeClient, redact_provider_text
from app.modules.free_model_discovery.repository import ActiveRunExistsError, FreeModelDiscoveryRepository
from app.modules.free_model_discovery.schemas import (
    FREE_MODEL_PROVIDERS,
    FreeModelCandidate,
    FreeModelCandidateGroup,
    FreeModelDiscoveryPlanResponse,
    FreeModelDiscoveryProviderProgress,
    FreeModelDiscoveryRunCounts,
    FreeModelDiscoveryRunItemResponse,
    FreeModelDiscoveryRunResponse,
    FreeModelDiscoveryRunsResponse,
    FreeModelDiscoveryRunSummary,
    FreeModelDiscoveryStartRequest,
    FreeModelItemState,
    FreeModelLimitScope,
    FreeModelProvider,
    FreeModelProviderPlan,
    FreeModelProviderPlanStatus,
    FreeModelRunStatus,
)
from app.modules.proxy.openrouter_sidecar_dispatch import openrouter_sidecar_config_from_settings
from app.modules.proxy.orcarouter_sidecar_dispatch import orcarouter_sidecar_config_from_settings
from app.modules.proxy.sidecar_routing import parse_sidecar_full_models
from app.modules.settings.repository import SettingsRepository

logger = logging.getLogger(__name__)

# Bounded retry for the pin write's compare-and-set. Contention is between one
# paced background append and an occasional operator save, so a couple of
# re-reads is ample; an unbounded loop would let a busy form starve the run.
_ADD_MODEL_MAX_ATTEMPTS = 3

# Frozen queue order inside a run: operator-facing priority.
_GROUP_ORDER = {"new": 0, "unresolved": 1, "due": 2, "cooldown": 3}

_FULL_MODELS_COLUMN = {
    "openrouter": "openrouter_sidecar_full_models_json",
    "orcarouter": "orcarouter_sidecar_full_models_json",
}


@dataclass(frozen=True, slots=True)
class ProviderAccess:
    status: FreeModelProviderPlanStatus
    message: str | None
    client: SidecarProbeClient | None
    # The resolved credential, carried so upstream-controlled error text can be
    # redacted before discovery persists it. ``None`` whenever ``client`` is.
    api_key: str | None = None


def provider_access(settings: DashboardSettings, provider: FreeModelProvider) -> ProviderAccess:
    """Resolve a provider's client from settings, or the reason it is unusable."""

    if provider == "openrouter":
        if not settings.openrouter_sidecar_enabled:
            return ProviderAccess("disabled", "OpenRouter sidecar is disabled", None)
        if settings.openrouter_sidecar_api_key_encrypted is None:
            return ProviderAccess("missing_api_key", "OpenRouter sidecar API key is not configured", None)
        openrouter_config = openrouter_sidecar_config_from_settings(settings)
        return ProviderAccess(
            "ok", None, OpenRouterSidecarClient(openrouter_config), api_key=openrouter_config.api_key
        )
    if not settings.orcarouter_sidecar_enabled:
        return ProviderAccess("disabled", "OrcaRouter sidecar is disabled", None)
    if settings.orcarouter_sidecar_api_key_encrypted is None:
        return ProviderAccess("missing_api_key", "OrcaRouter sidecar API key is not configured", None)
    orcarouter_config = orcarouter_sidecar_config_from_settings(settings)
    return ProviderAccess(
        "ok", None, get_orcarouter_sidecar_client(orcarouter_config), api_key=orcarouter_config.api_key
    )


def all_pinned_keys(settings: DashboardSettings) -> set[str]:
    """Every full-model id pinned by any sidecar, lowercased.

    The settings validator rejects one id pinned under two sidecars, so a
    candidate already pinned anywhere must be excluded, not just under its
    own provider.
    """

    columns = (
        settings.claude_sidecar_full_models_json,
        settings.openrouter_sidecar_full_models_json,
        settings.orcarouter_sidecar_full_models_json,
        settings.omniroute_sidecar_selected_models_json,
        settings.ollama_sidecar_full_models_json,
    )
    keys: set[str] = set()
    for raw in columns:
        for model_id in parse_sidecar_full_models(raw):
            keys.add(normalize_model_key(model_id))
    return keys


class FreeModelDiscoveryService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repository = FreeModelDiscoveryRepository(session)
        self._settings_repository = SettingsRepository(session)

    # --- plan -----------------------------------------------------------

    async def build_plan(self) -> FreeModelDiscoveryPlanResponse:
        now = utcnow()
        settings = await self._settings_repository.get_or_create()
        active = await self._repository.get_active_run()
        latest = await self._repository.get_latest_run()
        last_finished = latest if latest is not None and latest.status != "running" else None
        pinned = all_pinned_keys(settings)
        providers: list[FreeModelProviderPlan] = []
        for provider in FREE_MODEL_PROVIDERS:
            providers.append(await self._plan_provider(provider, settings, pinned, last_finished, now))
        return FreeModelDiscoveryPlanResponse(
            generated_at=now,
            providers=providers,
            active_run_id=active.id if active is not None else None,
        )

    async def _plan_provider(
        self,
        provider: FreeModelProvider,
        settings: DashboardSettings,
        pinned: set[str],
        last_finished: FreeModelDiscoveryRun | None,
        now: datetime,
    ) -> FreeModelProviderPlan:
        access = provider_access(settings, provider)
        if access.client is None:
            return FreeModelProviderPlan(provider=provider, status=access.status, message=access.message)
        try:
            # ``list_models`` (not ``list_models_cached``) so a transport failure
            # surfaces as a plan status instead of an empty candidate list.
            models = await access.client.list_models()
        except (OpenRouterSidecarUnavailableError, OrcaRouterSidecarUnavailableError) as exc:
            return FreeModelProviderPlan(
                provider=provider,
                status="unreachable",
                message=_sanitize(exc.message, api_key=access.api_key),
            )
        except (OpenRouterSidecarError, OrcaRouterSidecarError) as exc:
            return FreeModelProviderPlan(
                provider=provider, status="error", message=_sanitize(exc.message, api_key=access.api_key)
            )
        split = split_candidates(models, pinned)
        states = await self._repository.states_for_provider(provider)
        unresolved = await self._repository.unresolved_keys_for_provider(provider, run=last_finished)
        candidates = build_candidates(
            provider=provider,
            models=split.candidates,
            states=states,
            unresolved_keys=unresolved,
            now=now,
        )
        candidates.sort(key=lambda candidate: (_GROUP_ORDER[candidate.group], candidate.model_id.lower()))
        return FreeModelProviderPlan(
            provider=provider,
            status="ok",
            discovered_count=split.discovered_count,
            free_count=split.free_count,
            already_pinned_count=split.already_pinned_count,
            skipped_selector_count=split.skipped_selector_count,
            candidates=candidates,
        )

    # --- run lifecycle ----------------------------------------------------

    async def start_run(self, payload: FreeModelDiscoveryStartRequest) -> FreeModelDiscoveryRunResponse:
        """Freeze the confirmed selection into a run.

        The selection is re-validated against a fresh plan so a stale dialog
        cannot enqueue an id that is now pinned, or that no longer exists.
        """

        if await self._repository.get_active_run() is not None:
            raise DashboardConflictError("A discovery run is already in progress", code="discovery_run_active")
        plan = await self.build_plan()
        by_key: dict[tuple[str, str], FreeModelCandidate] = {}
        for provider_plan in plan.providers:
            for candidate in provider_plan.candidates:
                by_key[(candidate.provider, normalize_model_key(candidate.model_id))] = candidate
        chosen: list[FreeModelCandidate] = []
        for selection in payload.selections:
            candidate = by_key.get((selection.provider, normalize_model_key(selection.model_id)))
            if candidate is None:
                raise DashboardBadRequestError(
                    f"{selection.provider}/{selection.model_id} is not a current candidate; reload the plan",
                    code="discovery_selection_stale",
                )
            chosen.append(candidate)
        chosen.sort(key=lambda candidate: (_GROUP_ORDER[candidate.group], candidate.model_id.lower()))
        now = utcnow()
        try:
            run = await self._repository.create_run(
                started_at=now,
                deadline_at=now + DEFAULT_RUN_WALL_CLOCK,
                pacing_floor_seconds=DEFAULT_PACING_FLOOR_SECONDS,
                pacing_cap_seconds=DEFAULT_PACING_CAP_SECONDS,
                max_attempts_per_item=DEFAULT_MAX_ATTEMPTS_PER_ITEM,
                items=((candidate.provider, candidate.model_id, candidate.group) for candidate in chosen),
            )
        except ActiveRunExistsError as exc:
            # Lost the race against a concurrent start: the check above passed,
            # but ``build_plan`` calls provider APIs, so a second click can
            # arrive in between. Same answer as the pre-check, so a double
            # click is indistinguishable from a slow one to the caller.
            raise DashboardConflictError(
                "A discovery run is already in progress", code="discovery_run_active"
            ) from exc
        return await self.get_run(run.id)

    async def get_run(self, run_id: str) -> FreeModelDiscoveryRunResponse:
        run = await self._repository.get_run(run_id)
        if run is None:
            raise DashboardNotFoundError("Discovery run not found", code="discovery_run_not_found")
        items = await self._repository.list_items(run_id)
        return _run_response(run, items)

    async def get_active_or_latest_run(self) -> FreeModelDiscoveryRunResponse | None:
        run = await self._repository.get_active_run()
        if run is None:
            run = await self._repository.get_latest_run()
        if run is None:
            return None
        items = await self._repository.list_items(run.id)
        return _run_response(run, items)

    async def list_runs(self) -> FreeModelDiscoveryRunsResponse:
        active = await self._repository.get_active_run()
        runs = await self._repository.list_runs()
        summaries: list[FreeModelDiscoveryRunSummary] = []
        for run in runs:
            items = await self._repository.list_items(run.id)
            summaries.append(
                FreeModelDiscoveryRunSummary(
                    id=run.id,
                    status=_run_status(run.status),
                    started_at=run.started_at,
                    finished_at=run.finished_at,
                    counts=_counts(items),
                )
            )
        return FreeModelDiscoveryRunsResponse(active_run_id=active.id if active is not None else None, runs=summaries)

    async def cancel_run(self, run_id: str) -> FreeModelDiscoveryRunResponse:
        run = await self._repository.get_run(run_id)
        if run is None:
            raise DashboardNotFoundError("Discovery run not found", code="discovery_run_not_found")
        if run.status != "running":
            raise DashboardConflictError("Discovery run is not running", code="discovery_run_not_running")
        await self._repository.request_cancel(run_id)
        return await self.get_run(run_id)

    async def _reload_expired_caller_objects(self) -> None:
        """Re-load session instances a rollback expired, awaiting the I/O here.

        A rollback expires the whole identity map. The caller's run item is read
        synchronously after this service returns, and on an async session an
        implicit lazy load raises ``MissingGreenlet`` instead of querying, so the
        refresh has to happen while we can still await it.
        """

        for instance in list(self._session.identity_map.values()):
            if instance is None or not inspect(instance).expired:
                continue
            try:
                await self._session.refresh(instance)
            except Exception:  # pragma: no cover - instance deleted concurrently
                logger.debug("Could not refresh expired instance after settings conflict", exc_info=True)

    # --- pin write --------------------------------------------------------

    async def pin_full_model(self, provider: FreeModelProvider, model_id: str) -> bool:
        """Append a passed id to the provider's full-model list.

        Writes under the settings version CAS and re-reads/merges on conflict,
        so a concurrent operator save and this append cannot silently overwrite
        each other. An earlier revision used a version-lock-free UPDATE to avoid
        staling an open Settings form; that traded a form refresh for real data
        loss on a shared JSON column.

        Returns False when the id is already pinned anywhere, which is not an
        error, or when the write kept losing the CAS within its bounded retries.
        """

        column = _FULL_MODELS_COLUMN[provider]
        for attempt in range(_ADD_MODEL_MAX_ATTEMPTS):
            # Re-read inside the loop: on a conflict the other writer's version
            # of this column is what we must merge into, not the stale copy.
            #
            # Expire ONLY the settings row. ``expire_all()`` would also expire
            # the caller's loaded run item, whose attributes are read
            # synchronously right after this returns (``record_verdict``), and
            # on an async session that lazy reload raises rather than silently
            # querying. A conflict rollback expires the whole identity map for
            # the same reason, so the item is refreshed explicitly below.
            settings = await self._settings_repository.get_or_create()
            await self._session.refresh(settings)
            if normalize_model_key(model_id) in all_pinned_keys(settings):
                return False
            current = list(parse_sidecar_full_models(getattr(settings, column)))
            current.append(model_id.strip())
            try:
                await self._settings_repository.update_operational_json_column(
                    column, json.dumps(current, separators=(",", ":"))
                )
            except DashboardSettingsConflictError:
                # An operator (or another append) committed first. Their edit
                # stands; re-read and re-apply this id on top of it rather than
                # overwriting, which is what used to lose one side silently.
                #
                # The rollback inside commit_refresh expired every instance in
                # this session, including objects this service does not own, so
                # restore the ones the caller still uses before returning or
                # retrying.
                await self._reload_expired_caller_objects()
                if attempt == _ADD_MODEL_MAX_ATTEMPTS - 1:
                    logger.warning(
                        "Gave up pinning discovered model after %s version conflicts provider=%s",
                        _ADD_MODEL_MAX_ATTEMPTS,
                        provider,
                    )
                    raise
                continue
            await get_settings_cache().invalidate()
            return True
        return False


def _sanitize(message: str, *, api_key: str | None = None) -> str:
    """Redact provider credentials from upstream text shown in the plan.

    Previously this inserted ``[redacted]`` *after* the literal ``"Bearer "``
    and left the token itself in place, so it did not actually redact anything,
    and it never matched a bare key echoed without the prefix. Delegates to the
    same credential-aware contract the probe path uses.
    """

    return redact_provider_text(message, api_key=api_key)


def _run_status(value: str) -> FreeModelRunStatus:
    if value not in ("running", "completed", "cancelled", "expired", "failed"):
        raise RuntimeError(f"Unexpected discovery run status: {value}")
    return value


def _counts(items: Sequence[FreeModelDiscoveryRunItem]) -> FreeModelDiscoveryRunCounts:
    counts = FreeModelDiscoveryRunCounts(total=len(items))
    for item in items:
        if item.state == "queued":
            counts.queued += 1
            # A probed-and-requeued item is not an untouched one. Collapsing
            # the two is what let a live, retrying run read as "0 resolved".
            if item.attempts > 0:
                counts.retrying += 1
            else:
                counts.awaiting_first_attempt += 1
        elif item.state == "passed":
            counts.passed += 1
        elif item.state == "failed":
            counts.failed += 1
        elif item.state == "unresolved":
            counts.unresolved += 1
        if item.added_to_full_models:
            counts.added += 1
    return counts


def _run_response(
    run: FreeModelDiscoveryRun, items: Sequence[FreeModelDiscoveryRunItem]
) -> FreeModelDiscoveryRunResponse:
    from app.modules.free_model_discovery.runner import get_runner_progress

    progress = get_runner_progress(run.id)
    providers: list[FreeModelDiscoveryProviderProgress] = []
    for provider in FREE_MODEL_PROVIDERS:
        provider_items = [item for item in items if item.provider == provider]
        if not provider_items:
            continue
        live = progress.get(provider)
        # Process-local pacing state exists only while this process drives the
        # run. The persisted per-item scope is the fallback, so a restart or a
        # second replica still explains why the provider is waiting.
        persisted_scope = next(
            (
                item.last_limit_scope
                for item in provider_items
                if item.state == "queued" and item.last_limit_scope
            ),
            None,
        )
        providers.append(
            FreeModelDiscoveryProviderProgress(
                provider=provider,
                counts=_counts(provider_items),
                current_interval_seconds=live.current_interval_seconds if live is not None else None,
                next_probe_at=live.next_probe_at if live is not None else None,
                waiting_reason=live.waiting_reason if live is not None else None,
                limit_scope=cast(
                    "FreeModelLimitScope | None",
                    (live.limit_scope if live is not None and live.limit_scope else persisted_scope),
                ),
                provider_paused=bool(live.provider_paused) if live is not None else False,
            )
        )
    return FreeModelDiscoveryRunResponse(
        id=run.id,
        status=_run_status(run.status),
        started_at=run.started_at,
        finished_at=run.finished_at,
        deadline_at=run.deadline_at,
        cancel_requested=bool(run.cancel_requested),
        pacing_floor_seconds=run.pacing_floor_seconds,
        pacing_cap_seconds=run.pacing_cap_seconds,
        max_attempts_per_item=run.max_attempts_per_item,
        error_message=run.error_message,
        counts=_counts(items),
        providers=providers,
        items=[
            FreeModelDiscoveryRunItemResponse(
                provider=cast(FreeModelProvider, item.provider),
                model_id=item.model_id,
                group=cast(FreeModelCandidateGroup, item.candidate_group),
                state=cast(FreeModelItemState, item.state),
                attempts=item.attempts,
                limit_scope=cast("FreeModelLimitScope | None", item.last_limit_scope),
                next_attempt_at=item.next_attempt_at,
                last_attempt_at=item.last_attempt_at,
                last_http_status=item.last_http_status,
                last_outcome=item.last_outcome,
                content_chars=item.content_chars,
                content_ok_match=item.content_ok_match,
                reasoning_chars=item.reasoning_chars,
                added_to_full_models=bool(item.added_to_full_models),
                resolved_at=item.resolved_at,
            )
            for item in items
        ],
    )
