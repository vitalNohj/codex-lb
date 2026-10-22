from __future__ import annotations

<<<<<<< 22625a07e
import json
from collections.abc import Callable
from datetime import datetime
||||||| 84fde5a1e
from collections.abc import Callable
=======
from collections.abc import Callable, Sequence
>>>>>>> 72630bbfe

<<<<<<< 22625a07e
from sqlalchemy import delete, func, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
||||||| 84fde5a1e
=======
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
>>>>>>> 72630bbfe
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified
from sqlalchemy.orm.exc import StaleDataError

from app.core.auth.dashboard_session_ttl import DEFAULT_DASHBOARD_SESSION_TTL_SECONDS
<<<<<<< 22625a07e
from app.core.config.settings import get_settings
from app.core.config.sidecar_prefix_seed import dump_configured_sidecar_prefixes
from app.core.crypto import TokenEncryptor
||||||| 84fde5a1e
from app.core.config.settings import get_settings
=======
>>>>>>> 72630bbfe
from app.core.exceptions import DashboardSettingsConflictError
from app.core.upstream_proxy.cache import get_upstream_route_cache
<<<<<<< 22625a07e
from app.db.models import (
    ClaudeHaiku55PinOwnership,
    ClaudeOpus55PinOwnership,
    ClaudeSonnet55PinOwnership,
    DashboardSettings,
)
from app.modules.settings.dashboard_layout import DEFAULT_DASHBOARD_LAYOUT_JSON
||||||| 84fde5a1e
from app.db.models import DashboardSettings
=======
from app.db.models import DashboardSettings, DashboardUser, LocalLoginPolicy, ModelContextWindowOverride
from app.modules.dashboard_users.repository import DashboardUsersRepository
>>>>>>> 72630bbfe

_SETTINGS_ID = 1
_UNSET = object()
# Pinned onto the CLIProxyAPI full-model list by
# 20260923_000000_pin_claude_opus_5_5_full_model,
# 20260928_000000_pin_claude_sonnet_5_5_full_model, and
# 20261007_000000_pin_claude_haiku_5_5_full_model.
_CLAUDE_OPUS_5_5_PIN = "claude-opus-5-5"
_CLAUDE_SONNET_5_5_PIN = "claude-sonnet-5-5"
_CLAUDE_HAIKU_5_5_PIN = "claude-haiku-5-5"
_PinOwnership = type[ClaudeOpus55PinOwnership] | type[ClaudeSonnet55PinOwnership] | type[ClaudeHaiku55PinOwnership]


def _lists_full_model(full_models_json: str, model_id: str) -> bool:
    """Whether the saved list holds ``model_id``, matched the way the pin migrations match it."""
    try:
        entries = json.loads(full_models_json)
    except json.JSONDecodeError:
        return False
    if not isinstance(entries, list):
        return False
    return any(isinstance(entry, str) and entry.strip().lower() == model_id for entry in entries)


_OPERATIONAL_JSON_COLUMNS = frozenset(
    {
        "openrouter_sidecar_full_models_json",
        "orcarouter_sidecar_full_models_json",
    }
)

# Operational JSON columns written WITHOUT bumping ``version``, under a
# compare-and-set on the column's own value instead. See
# ``update_operational_json_column_if_unchanged`` for why both properties are
# needed at once.
_OPERATIONAL_JSON_CAS_COLUMNS = frozenset({"openai_compat_endpoints_json"})


class SettingsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_active_password_users(self) -> Sequence[DashboardUser]:
        """Accounts the TOTP requirements bind (roles loaded for the admin-level check)."""

        return await DashboardUsersRepository(self._session).list_active_local_password_users()

    async def acquire_account_write_intent(self) -> None:
        """Serialise this settings write against the account mutations it depends on.

        The tightening gate counts qualifying emergency accounts and then
        writes the policy; without the accounts lock a concurrent TOTP reset,
        password removal or deactivation can take the last one away in between
        and leave a restricted policy with no way back in.
        """

        await DashboardUsersRepository(self._session).acquire_write_intent()

    async def count_qualifying_break_glass(self) -> int:
        """Accounts that can still open the door once local sign-in is restricted."""

        return await DashboardUsersRepository(self._session).count_qualifying_break_glass()

    async def list_break_glass_designations(self) -> Sequence[DashboardUser]:
        """Designated accounts, so a refusal can name the one an operator should enrol."""

        return await DashboardUsersRepository(self._session).list_break_glass_designations()

    async def get_or_create(self) -> DashboardSettings:
        existing = await self._session.get(DashboardSettings, _SETTINGS_ID)
        if existing is not None:
            return existing

        static_settings = get_settings()
        sidecar_api_key = static_settings.claude_sidecar_api_key.strip()
        sidecar_management_key = static_settings.claude_sidecar_management_key.strip()
        row = DashboardSettings(
            id=_SETTINGS_ID,
            sticky_threads_enabled=True,
            upstream_stream_transport="auto",
            prohibit_fast_mode=False,
            # Account-capacity overrides are tri-state: NULL inherits the
            # process environment value at read time. The first-boot seed must
            # stay NULL — copying the env value here would freeze it as a
            # dashboard override while the UI keeps labelling the (possibly
            # changed) env value as the inherited baseline.
            proxy_account_response_create_limit=None,
            proxy_account_stream_limit=None,
            proxy_account_stream_recovery_reserve=None,
            proxy_api_key_fair_share_congestion_threshold_pct=None,
            # Thread cache identity: same tri-state rule, seeded NULL.
            # NULL inherits the environment value and then ``shared``.
            thread_cache_identity_mode=None,
            # C2-2 routing/overload: same tri-state rule, seeded NULL.
            proxy_overload_isolation_seconds=None,
            proxy_account_error_rate_weighting_enabled=None,
            proxy_account_inflight_penalty_pct=None,
            proxy_account_lease_token_weight=None,
            proxy_account_lease_ttl_seconds=None,
            upstream_proxy_routing_enabled=False,
            upstream_proxy_default_pool_id=None,
            prefer_earlier_reset_accounts=True,
            prefer_earlier_reset_window="secondary",
            show_reset_credit_badges=True,
            auto_redeem_reset_credits_before_expiry=False,
            show_reset_credit_expiry_badge=True,
            routing_strategy="capacity_weighted",
            relative_availability_power=2.0,
            relative_availability_top_k=5,
            single_account_id=None,
<<<<<<< 22625a07e
            openai_cache_affinity_max_age_seconds=static_settings.openai_cache_affinity_max_age_seconds,
||||||| 84fde5a1e
            openai_cache_affinity_max_age_seconds=get_settings().openai_cache_affinity_max_age_seconds,
=======
>>>>>>> 72630bbfe
            dashboard_session_ttl_seconds=DEFAULT_DASHBOARD_SESSION_TTL_SECONDS,
<<<<<<< 22625a07e
            warmup_model=static_settings.warmup_model,
||||||| 84fde5a1e
            warmup_model=get_settings().warmup_model,
=======
>>>>>>> 72630bbfe
            import_without_overwrite=True,
            totp_required_on_login=False,
            totp_required_for_admin_role=False,
            local_login_policy=LocalLoginPolicy.ENABLED.value,
            guest_access_enabled=False,
            guest_password_hash=None,
            bootstrap_token_encrypted=None,
            bootstrap_token_hash=None,
            api_key_auth_enabled=False,
            hide_upstream_quota_from_api_keys=False,
            sticky_reallocation_primary_budget_threshold_pct=95.0,
            sticky_reallocation_secondary_budget_threshold_pct=100.0,
            additional_quota_routing_policies_json="{}",
            model_aliases_json="{}",
            custom_alias_catalog_json="{}",
            limit_warmup_enabled=False,
            limit_warmup_windows="both",
            limit_warmup_model="auto",
            limit_warmup_prompt="Say OK.",
            limit_warmup_cooldown_seconds=3600,
            limit_warmup_exhausted_threshold_percent=99.0,
            limit_warmup_idle_threshold_percent=1.0,
            limit_warmup_min_available_percent=100.0,
            weekly_pace_working_days="0,1,2,3,4,5,6",
            weekly_pace_smoothing_minutes=30,
            claude_sidecar_enabled=static_settings.claude_sidecar_enabled,
            claude_sidecar_base_url=static_settings.claude_sidecar_base_url,
            claude_sidecar_api_key_encrypted=TokenEncryptor().encrypt(sidecar_api_key) if sidecar_api_key else None,
            claude_sidecar_model_prefixes_json=json.dumps(
                [
                    {"prefix": prefix.strip().lower(), "strip": prefix.strip().endswith(("-", "_"))}
                    for prefix in static_settings.claude_sidecar_model_prefixes
                    if prefix.strip()
                ],
                separators=(",", ":"),
            ),
            claude_sidecar_full_models_json="[]",
            claude_sidecar_connect_timeout_seconds=static_settings.claude_sidecar_connect_timeout_seconds,
            claude_sidecar_request_timeout_seconds=static_settings.claude_sidecar_request_timeout_seconds,
            claude_sidecar_models_cache_ttl_seconds=static_settings.claude_sidecar_models_cache_ttl_seconds,
            claude_sidecar_management_key_encrypted=(
                TokenEncryptor().encrypt(sidecar_management_key) if sidecar_management_key else None
            ),
            claude_sidecar_quota_poll_interval_seconds=static_settings.claude_sidecar_quota_poll_interval_seconds,
            claude_sidecar_auth_plans_json="[]",
            claude_sidecar_usage_poll_interval_seconds=static_settings.claude_sidecar_usage_poll_interval_seconds,
            claude_sidecar_usage_queue_batch_size=static_settings.claude_sidecar_usage_queue_batch_size,
            claude_sidecar_usage_collection_enabled=static_settings.claude_sidecar_usage_collection_enabled,
            openrouter_sidecar_enabled=static_settings.openrouter_sidecar_enabled,
            openrouter_sidecar_base_url=static_settings.openrouter_sidecar_base_url,
            openrouter_sidecar_api_key_encrypted=(
                TokenEncryptor().encrypt(static_settings.openrouter_sidecar_api_key.strip())
                if static_settings.openrouter_sidecar_api_key.strip()
                else None
            ),
            openrouter_sidecar_model_prefixes_json=json.dumps(
                [
                    {"prefix": prefix.strip().lower(), "strip": prefix.strip().endswith(("-", "_"))}
                    for prefix in static_settings.openrouter_sidecar_model_prefixes
                    if prefix.strip()
                ],
                separators=(",", ":"),
            ),
            openrouter_sidecar_full_models_json="[]",
            openrouter_sidecar_connect_timeout_seconds=static_settings.openrouter_sidecar_connect_timeout_seconds,
            openrouter_sidecar_request_timeout_seconds=static_settings.openrouter_sidecar_request_timeout_seconds,
            openrouter_sidecar_models_cache_ttl_seconds=static_settings.openrouter_sidecar_models_cache_ttl_seconds,
            openai_compat_endpoints_json="[]",
            orcarouter_sidecar_enabled=static_settings.orcarouter_sidecar_enabled,
            orcarouter_sidecar_base_url=static_settings.orcarouter_sidecar_base_url,
            orcarouter_sidecar_api_key_encrypted=(
                TokenEncryptor().encrypt(static_settings.orcarouter_sidecar_api_key.strip())
                if static_settings.orcarouter_sidecar_api_key.strip()
                else None
            ),
            # The ``orcarouter/`` seed lives in the settings default, so an
            # absent CODEX_LB_ORCAROUTER_SIDECAR_MODEL_PREFIXES still seeds it
            # while an explicitly emptied value is honoured as empty. Falling
            # back here instead would re-seed an active prefix for the operator
            # who cleared it precisely because OmniRoute owns ``orcarouter/``,
            # making the next settings PUT fail closed with 400
            # ``sidecar_routing_conflict``. The migration's fresh-install seed
            # shares this helper so both entry points agree.
            orcarouter_sidecar_model_prefixes_json=dump_configured_sidecar_prefixes(
                static_settings.orcarouter_sidecar_model_prefixes
            ),
            orcarouter_sidecar_full_models_json="[]",
            orcarouter_sidecar_connect_timeout_seconds=static_settings.orcarouter_sidecar_connect_timeout_seconds,
            orcarouter_sidecar_request_timeout_seconds=static_settings.orcarouter_sidecar_request_timeout_seconds,
            orcarouter_sidecar_models_cache_ttl_seconds=static_settings.orcarouter_sidecar_models_cache_ttl_seconds,
            opencode_go_sidecar_enabled=static_settings.opencode_go_sidecar_enabled,
            opencode_go_sidecar_base_url=static_settings.opencode_go_sidecar_base_url,
            opencode_go_sidecar_api_key_encrypted=(
                TokenEncryptor().encrypt(static_settings.opencode_go_sidecar_api_key.strip())
                if static_settings.opencode_go_sidecar_api_key.strip()
                else None
            ),
            # Same rule as OrcaRouter: the ``opencode-go/`` seed lives in the
            # settings default, so an absent
            # CODEX_LB_OPENCODE_GO_SIDECAR_MODEL_PREFIXES still seeds it while an
            # explicitly emptied value is honoured as empty. The migration's
            # fresh-install seed shares this helper so both entry points agree.
            opencode_go_sidecar_model_prefixes_json=dump_configured_sidecar_prefixes(
                static_settings.opencode_go_sidecar_model_prefixes
            ),
            opencode_go_sidecar_full_models_json="[]",
            opencode_go_sidecar_connect_timeout_seconds=static_settings.opencode_go_sidecar_connect_timeout_seconds,
            opencode_go_sidecar_request_timeout_seconds=static_settings.opencode_go_sidecar_request_timeout_seconds,
            opencode_go_sidecar_models_cache_ttl_seconds=static_settings.opencode_go_sidecar_models_cache_ttl_seconds,
            omniroute_sidecar_enabled=static_settings.omniroute_sidecar_enabled,
            omniroute_sidecar_base_url=static_settings.omniroute_sidecar_base_url,
            omniroute_sidecar_api_key_encrypted=(
                TokenEncryptor().encrypt(static_settings.omniroute_sidecar_api_key.strip())
                if static_settings.omniroute_sidecar_api_key.strip()
                else None
            ),
            omniroute_sidecar_selected_models_json=json.dumps(
                static_settings.omniroute_sidecar_selected_models,
                separators=(",", ":"),
            ),
            omniroute_sidecar_prefixes_json="[]",
            omniroute_sidecar_connect_timeout_seconds=static_settings.omniroute_sidecar_connect_timeout_seconds,
            omniroute_sidecar_request_timeout_seconds=static_settings.omniroute_sidecar_request_timeout_seconds,
            omniroute_sidecar_models_cache_ttl_seconds=static_settings.omniroute_sidecar_models_cache_ttl_seconds,
            ollama_sidecar_enabled=static_settings.ollama_sidecar_enabled,
            ollama_sidecar_base_url=static_settings.ollama_sidecar_base_url,
            ollama_sidecar_api_key_encrypted=(
                TokenEncryptor().encrypt(static_settings.ollama_sidecar_api_key.strip())
                if static_settings.ollama_sidecar_api_key.strip()
                else None
            ),
            ollama_sidecar_model_prefixes_json=json.dumps(
                [
                    {"prefix": prefix.strip().lower(), "strip": prefix.strip().endswith(("-", "_"))}
                    for prefix in static_settings.ollama_sidecar_model_prefixes
                    if prefix.strip()
                ],
                separators=(",", ":"),
            ),
            ollama_sidecar_full_models_json=json.dumps(
                static_settings.ollama_sidecar_full_models,
                separators=(",", ":"),
            ),
            ollama_sidecar_connect_timeout_seconds=static_settings.ollama_sidecar_connect_timeout_seconds,
            ollama_sidecar_request_timeout_seconds=static_settings.ollama_sidecar_request_timeout_seconds,
            ollama_sidecar_models_cache_ttl_seconds=static_settings.ollama_sidecar_models_cache_ttl_seconds,
            limit_warmup_staggered_idle_enabled=False,
            request_log_retention_days=None,
            usage_history_retention_days=None,
<<<<<<< 22625a07e
            hourly_rollup_retention_days=None,
            dashboard_layout_json=DEFAULT_DASHBOARD_LAYOUT_JSON,
||||||| 84fde5a1e
=======
            # C2-3 resilience toggles: NULL = inherit the env alias / default.
            soft_drain_enabled=None,
            deterministic_failover_enabled=None,
            circuit_breaker_enabled=None,
            # M3 codex prewarm: NULL = inherit the env alias / default (off).
            http_responses_session_bridge_codex_prewarm_enabled=None,
            # M2 background jobs: NULL = inherit the env alias / default.
            auth_guardian_enabled=None,
            automations_scheduler_enabled=None,
            rate_limit_reset_credits_refresh_enabled=None,
            # M5 conversation archive: NULL = inherit the env alias / default.
            conversation_archive_enabled=None,
            # R2 spool retention: NULL = inherit the env alias / default (7d).
            http_responses_session_bridge_operation_spool_retention_seconds=None,
>>>>>>> 72630bbfe
        )
        self._session.add(row)
        try:
            await self._session.commit()
        except IntegrityError:
            await self._session.rollback()
            existing = await self._session.get(DashboardSettings, _SETTINGS_ID)
            if existing is None:
                raise
            return existing
        await self._session.refresh(row)
        return row

    async def get_fresh(self) -> DashboardSettings:
        """Return settings reloaded from a new read snapshot.

        ORM-clean sessions COMMIT first. That ends the SQLite read snapshot
        so concurrent poller commits are visible, and a later Core UPDATE
        on this session does not hit SQLITE_BUSY_SNAPSHOT.

        Sessions with pending ORM writes skip COMMIT and skip nested
        sessions. StaticPool in-memory SQLite would share the caller's
        connection and ROLLBACK on close; a second file-SQLite connection
        can deadlock on the writer lock. Return the identity-map row.
        Pause/resume is ORM-clean and takes the COMMIT path.

        Core UPDATE via session.execute() is invisible to dirty/new/deleted.
        Callers MUST NOT leave uncommitted Core UPDATEs when calling
        get_fresh. update_operational already COMMITs.
        """
        if self._session.dirty or self._session.new or self._session.deleted:
            existing = await self._session.get(DashboardSettings, _SETTINGS_ID)
            if existing is None:
                raise RuntimeError("get_fresh cannot create settings while the session is dirty")
            return existing
        await self._session.commit()
        row = await self.get_or_create()
        await self._session.refresh(row)
        return row

    async def update_operational(
        self,
        *,
        claude_sidecar_last_health_status: str | None | object = _UNSET,
        claude_sidecar_last_health_message: str | None | object = _UNSET,
        claude_sidecar_last_checked_at: datetime | None | object = _UNSET,
        claude_sidecar_last_model_count: int | None | object = _UNSET,
        claude_sidecar_quota_state_json: str | None | object = _UNSET,
        claude_sidecar_quota_checked_at: datetime | None | object = _UNSET,
        openrouter_sidecar_last_health_status: str | None | object = _UNSET,
        openrouter_sidecar_last_health_message: str | None | object = _UNSET,
        openrouter_sidecar_last_checked_at: datetime | None | object = _UNSET,
        openrouter_sidecar_last_model_count: int | None | object = _UNSET,
        openai_compat_endpoints_json: str | None | object = _UNSET,
        orcarouter_sidecar_last_health_status: str | None | object = _UNSET,
        orcarouter_sidecar_last_health_message: str | None | object = _UNSET,
        orcarouter_sidecar_last_checked_at: datetime | None | object = _UNSET,
        orcarouter_sidecar_last_model_count: int | None | object = _UNSET,
        opencode_go_sidecar_last_health_status: str | None | object = _UNSET,
        opencode_go_sidecar_last_health_message: str | None | object = _UNSET,
        opencode_go_sidecar_last_checked_at: datetime | None | object = _UNSET,
        opencode_go_sidecar_last_model_count: int | None | object = _UNSET,
        omniroute_sidecar_last_health_status: str | None | object = _UNSET,
        omniroute_sidecar_last_health_message: str | None | object = _UNSET,
        omniroute_sidecar_last_checked_at: datetime | None | object = _UNSET,
        omniroute_sidecar_last_model_count: int | None | object = _UNSET,
        ollama_sidecar_last_health_status: str | None | object = _UNSET,
        ollama_sidecar_last_health_message: str | None | object = _UNSET,
        ollama_sidecar_last_checked_at: datetime | None | object = _UNSET,
        ollama_sidecar_last_model_count: int | None | object = _UNSET,
    ) -> DashboardSettings:
        """Persist sidecar health/quota columns without bumping ``version``.

        Quota polling and test-connection results share ``dashboard_settings``
        with operator saves. Routing those writes through ``version_id_col``
        makes an open Settings form's ``expectedVersion`` stale on the next
        poll. A Core UPDATE leaves the optimistic lock for operator PUTs.
        """
        candidates = {
            "claude_sidecar_last_health_status": claude_sidecar_last_health_status,
            "claude_sidecar_last_health_message": claude_sidecar_last_health_message,
            "claude_sidecar_last_checked_at": claude_sidecar_last_checked_at,
            "claude_sidecar_last_model_count": claude_sidecar_last_model_count,
            "claude_sidecar_quota_state_json": claude_sidecar_quota_state_json,
            "claude_sidecar_quota_checked_at": claude_sidecar_quota_checked_at,
            "openrouter_sidecar_last_health_status": openrouter_sidecar_last_health_status,
            "openrouter_sidecar_last_health_message": openrouter_sidecar_last_health_message,
            "openrouter_sidecar_last_checked_at": openrouter_sidecar_last_checked_at,
            "openrouter_sidecar_last_model_count": openrouter_sidecar_last_model_count,
            "openai_compat_endpoints_json": openai_compat_endpoints_json,
            "orcarouter_sidecar_last_health_status": orcarouter_sidecar_last_health_status,
            "orcarouter_sidecar_last_health_message": orcarouter_sidecar_last_health_message,
            "orcarouter_sidecar_last_checked_at": orcarouter_sidecar_last_checked_at,
            "orcarouter_sidecar_last_model_count": orcarouter_sidecar_last_model_count,
            "opencode_go_sidecar_last_health_status": opencode_go_sidecar_last_health_status,
            "opencode_go_sidecar_last_health_message": opencode_go_sidecar_last_health_message,
            "opencode_go_sidecar_last_checked_at": opencode_go_sidecar_last_checked_at,
            "opencode_go_sidecar_last_model_count": opencode_go_sidecar_last_model_count,
            "omniroute_sidecar_last_health_status": omniroute_sidecar_last_health_status,
            "omniroute_sidecar_last_health_message": omniroute_sidecar_last_health_message,
            "omniroute_sidecar_last_checked_at": omniroute_sidecar_last_checked_at,
            "omniroute_sidecar_last_model_count": omniroute_sidecar_last_model_count,
            "ollama_sidecar_last_health_status": ollama_sidecar_last_health_status,
            "ollama_sidecar_last_health_message": ollama_sidecar_last_health_message,
            "ollama_sidecar_last_checked_at": ollama_sidecar_last_checked_at,
            "ollama_sidecar_last_model_count": ollama_sidecar_last_model_count,
        }
        values = {column: value for column, value in candidates.items() if value is not _UNSET}
        settings = await self.get_or_create()
        if not values:
            return settings
        values["updated_at"] = func.now()
        await self._session.execute(
            update(DashboardSettings).where(DashboardSettings.id == _SETTINGS_ID).values(**values)
        )
        await self._session.commit()
        await self._session.refresh(settings)
        return settings

    async def update_operational_json_column_if_unchanged(
        self, column: str, *, expected: str | None, value: str
    ) -> bool:
        """Write one operational JSON column only if it still holds ``expected``.

        Returns ``True`` on success and ``False`` when another writer changed the
        column first, so the caller can re-read and re-apply its own narrow edit.

        This column needs two properties that no existing path offers together:

        * **It must not bump ``version``.** ``openai_compat_endpoints_json`` is a
          collection the Settings form edits, and the form's optimistic-version
          check refuses a save whose snapshot is stale. Recording a health result
          - an operator pressing one endpoint card's Test button - must not make
          the form they are already editing refuse to save. This is the same
          reasoning ``update_operational`` documents, and an existing test pins
          it.
        * **It must not be a blind whole-blob overwrite.** The same blob holds
          every endpoint's *configuration* as well as its health, so a write
          built from a stale read silently reverts a concurrent endpoint edit or
          another endpoint's test result.

        A compare-and-set on the column's own value satisfies both: it detects
        exactly the interference that matters (someone else changed this blob)
        while leaving the row's ``version`` - and therefore every open form -
        alone. The Core UPDATE is dialect-agnostic and needs no row lock, because
        the ``WHERE`` clause is evaluated by the database at write time.
        """

        if column not in _OPERATIONAL_JSON_CAS_COLUMNS:
            raise ValueError(f"column {column!r} is not a compare-and-set operational JSON column")
        settings_column = getattr(DashboardSettings, column)
        # ``expected`` may legitimately be NULL (the column has never been
        # written), and ``= NULL`` matches nothing in SQL, so branch on it.
        current_matches = settings_column.is_(None) if expected is None else settings_column == expected
        result = await self._session.execute(
            update(DashboardSettings)
            .where(DashboardSettings.id == _SETTINGS_ID)
            .where(current_matches)
            .values(**{column: value, "updated_at": func.now()})
        )
        await self._session.commit()
        # ``getattr`` rather than a direct attribute read: ``rowcount`` is not on
        # the generic ``Result`` type, the same accommodation the other
        # affected-row checks in this codebase make.
        if int(getattr(result, "rowcount", 0) or 0) <= 0:
            return False
        settings = await self.get_or_create()
        await self._session.refresh(settings)
        return True

    async def update_operational_json_column(self, column: str, value: str) -> DashboardSettings:
        """Persist one sidecar full-model JSON column under the version CAS.

        An earlier revision wrote this column with an unconditional UPDATE so a
        multi-hour discovery run would not stale an open Settings form. That
        traded a form refresh for **silent data loss**: the column is a JSON
        blob, so a read-modify-write here and a concurrent operator save of the
        same column each overwrite the other's edit, losing either a discovered
        pin or the operator's change.

        The write now goes through the same optimistic ``version`` column as
        every other settings write. Callers that append (discovery) re-read and
        merge on conflict rather than overwriting; an operator's stale form
        still receives the explicit 409 it already handles.
        """
        if column not in _OPERATIONAL_JSON_COLUMNS:
            raise ValueError(f"column {column!r} is not an operational JSON column")
        settings = await self.get_or_create()
        setattr(settings, column, value)
        settings.updated_at = func.now()
        # commit_refresh emits `UPDATE ... WHERE version = :loaded`, so a writer
        # that committed in between surfaces as StaleDataError -> 409 instead of
        # silently clobbering the other side.
        await self.commit_refresh(settings)
        return settings

    async def update(
        self,
        *,
        sticky_threads_enabled: bool | None = None,
        cliproxy_capacity_routing_enabled: bool | None = None,
        upstream_stream_transport: str | None = None,
        prohibit_fast_mode: bool | None = None,
        http_downstream_transport_policy: str | None = None,
        thread_cache_identity_mode: str | None = None,
        clear_thread_cache_identity_mode: bool = False,
        proxy_account_response_create_limit: int | None = None,
        clear_proxy_account_response_create_limit: bool = False,
        proxy_account_stream_limit: int | None = None,
        clear_proxy_account_stream_limit: bool = False,
        proxy_account_stream_recovery_reserve: int | None = None,
        clear_proxy_account_stream_recovery_reserve: bool = False,
        proxy_api_key_fair_share_congestion_threshold_pct: int | None = None,
        clear_proxy_api_key_fair_share_congestion_threshold_pct: bool = False,
        # C2-2 routing/overload
        proxy_overload_isolation_seconds: int | None = None,
        clear_proxy_overload_isolation_seconds: bool = False,
        proxy_account_error_rate_weighting_enabled: bool | None = None,
        clear_proxy_account_error_rate_weighting_enabled: bool = False,
        proxy_account_inflight_penalty_pct: float | None = None,
        clear_proxy_account_inflight_penalty_pct: bool = False,
        proxy_account_lease_token_weight: float | None = None,
        clear_proxy_account_lease_token_weight: bool = False,
        proxy_account_lease_ttl_seconds: float | None = None,
        clear_proxy_account_lease_ttl_seconds: bool = False,
        # end C2-2 routing/overload
        upstream_proxy_routing_enabled: bool | None = None,
        upstream_proxy_default_pool_id: str | None | object = _UNSET,
        prefer_earlier_reset_accounts: bool | None = None,
        prefer_earlier_reset_window: str | None = None,
        show_reset_credit_badges: bool | None = None,
        auto_redeem_reset_credits_before_expiry: bool | None = None,
        show_reset_credit_expiry_badge: bool | None = None,
        routing_strategy: str | None = None,
        relative_availability_power: float | None = None,
        relative_availability_top_k: int | None = None,
        single_account_id: str | None = None,
        openai_cache_affinity_max_age_seconds: int | None = None,
        dashboard_session_ttl_seconds: int | None = None,
        http_responses_session_bridge_prompt_cache_idle_ttl_seconds: int | None = None,
        http_responses_session_bridge_gateway_safe_mode: bool | None = None,
        sticky_reallocation_budget_threshold_pct: float | None = None,
        sticky_reallocation_primary_budget_threshold_pct: float | None = None,
        sticky_reallocation_secondary_budget_threshold_pct: float | None = None,
        additional_quota_routing_policies_json: str | None = None,
        model_aliases_json: str | None = None,
        custom_alias_catalog_json: str | None = None,
        warmup_model: str | None = None,
        import_without_overwrite: bool | None = None,
        totp_required_on_login: bool | None = None,
        totp_required_for_admin_role: bool | None = None,
        local_login_policy: str | None = None,
        api_key_auth_enabled: bool | None = None,
        hide_upstream_quota_from_api_keys: bool | None = None,
        limit_warmup_enabled: bool | None = None,
        limit_warmup_windows: str | None = None,
        limit_warmup_model: str | None = None,
        limit_warmup_prompt: str | None = None,
        limit_warmup_cooldown_seconds: int | None = None,
        limit_warmup_exhausted_threshold_percent: float | None = None,
        limit_warmup_idle_threshold_percent: float | None = None,
        limit_warmup_min_available_percent: float | None = None,
        weekly_pace_working_days: str | None = None,
        weekly_pace_smoothing_minutes: int | None = None,
        claude_sidecar_enabled: bool | None = None,
        claude_sidecar_base_url: str | None = None,
        claude_sidecar_api_key_encrypted: bytes | None | object = _UNSET,
        claude_sidecar_model_prefixes_json: str | None = None,
        claude_sidecar_full_models_json: str | None = None,
        claude_sidecar_connect_timeout_seconds: float | None = None,
        claude_sidecar_request_timeout_seconds: float | None = None,
        claude_sidecar_models_cache_ttl_seconds: float | None = None,
        claude_sidecar_last_health_status: str | None | object = _UNSET,
        claude_sidecar_last_health_message: str | None | object = _UNSET,
        claude_sidecar_last_checked_at: datetime | None | object = _UNSET,
        claude_sidecar_last_model_count: int | None | object = _UNSET,
        claude_sidecar_management_key_encrypted: bytes | None | object = _UNSET,
        claude_sidecar_quota_poll_interval_seconds: float | None = None,
        claude_sidecar_quota_state_json: str | None | object = _UNSET,
        claude_sidecar_quota_checked_at: datetime | None | object = _UNSET,
        claude_sidecar_auth_plans_json: str | None = None,
        claude_sidecar_usage_poll_interval_seconds: float | None = None,
        claude_sidecar_usage_queue_batch_size: int | None = None,
        claude_sidecar_usage_collection_enabled: bool | None = None,
        claude_sidecar_default_reasoning_effort: str | None | object = _UNSET,
        openrouter_sidecar_enabled: bool | None = None,
        openrouter_sidecar_base_url: str | None = None,
        openrouter_sidecar_api_key_encrypted: bytes | None | object = _UNSET,
        openrouter_sidecar_model_prefixes_json: str | None = None,
        openrouter_sidecar_full_models_json: str | None = None,
        openrouter_sidecar_connect_timeout_seconds: float | None = None,
        openrouter_sidecar_request_timeout_seconds: float | None = None,
        openrouter_sidecar_models_cache_ttl_seconds: float | None = None,
        openrouter_sidecar_last_health_status: str | None | object = _UNSET,
        openrouter_sidecar_last_health_message: str | None | object = _UNSET,
        openrouter_sidecar_last_checked_at: datetime | None | object = _UNSET,
        openrouter_sidecar_last_model_count: int | None | object = _UNSET,
        openrouter_sidecar_default_reasoning_effort: str | None | object = _UNSET,
        openai_compat_endpoints_json: str | None = None,
        orcarouter_sidecar_enabled: bool | None = None,
        orcarouter_sidecar_base_url: str | None = None,
        orcarouter_sidecar_api_key_encrypted: bytes | None | object = _UNSET,
        orcarouter_sidecar_model_prefixes_json: str | None = None,
        orcarouter_sidecar_full_models_json: str | None = None,
        orcarouter_sidecar_connect_timeout_seconds: float | None = None,
        orcarouter_sidecar_request_timeout_seconds: float | None = None,
        orcarouter_sidecar_models_cache_ttl_seconds: float | None = None,
        orcarouter_sidecar_last_health_status: str | None | object = _UNSET,
        orcarouter_sidecar_last_health_message: str | None | object = _UNSET,
        orcarouter_sidecar_last_checked_at: datetime | None | object = _UNSET,
        orcarouter_sidecar_last_model_count: int | None | object = _UNSET,
        orcarouter_sidecar_default_reasoning_effort: str | None | object = _UNSET,
        opencode_go_sidecar_enabled: bool | None = None,
        opencode_go_sidecar_base_url: str | None = None,
        opencode_go_sidecar_api_key_encrypted: bytes | None | object = _UNSET,
        opencode_go_sidecar_model_prefixes_json: str | None = None,
        opencode_go_sidecar_full_models_json: str | None = None,
        opencode_go_sidecar_connect_timeout_seconds: float | None = None,
        opencode_go_sidecar_request_timeout_seconds: float | None = None,
        opencode_go_sidecar_models_cache_ttl_seconds: float | None = None,
        omniroute_sidecar_enabled: bool | None = None,
        omniroute_sidecar_base_url: str | None = None,
        omniroute_sidecar_api_key_encrypted: bytes | None | object = _UNSET,
        omniroute_sidecar_selected_models_json: str | None = None,
        omniroute_sidecar_prefixes_json: str | None = None,
        omniroute_sidecar_connect_timeout_seconds: float | None = None,
        omniroute_sidecar_request_timeout_seconds: float | None = None,
        omniroute_sidecar_models_cache_ttl_seconds: float | None = None,
        omniroute_sidecar_last_health_status: str | None | object = _UNSET,
        omniroute_sidecar_last_health_message: str | None | object = _UNSET,
        omniroute_sidecar_last_checked_at: datetime | None | object = _UNSET,
        omniroute_sidecar_last_model_count: int | None | object = _UNSET,
        omniroute_sidecar_default_reasoning_effort: str | None | object = _UNSET,
        ollama_sidecar_enabled: bool | None = None,
        ollama_sidecar_base_url: str | None = None,
        ollama_sidecar_api_key_encrypted: bytes | None | object = _UNSET,
        ollama_sidecar_model_prefixes_json: str | None = None,
        ollama_sidecar_full_models_json: str | None = None,
        ollama_sidecar_connect_timeout_seconds: float | None = None,
        ollama_sidecar_request_timeout_seconds: float | None = None,
        ollama_sidecar_models_cache_ttl_seconds: float | None = None,
        # Lower-cased full model -> provider key of the integration starred as
        # the model's default route; ``None`` keeps the stored map.
        sidecar_full_model_stars_json: str | None = None,
        ollama_sidecar_last_health_status: str | None | object = _UNSET,
        ollama_sidecar_last_health_message: str | None | object = _UNSET,
        ollama_sidecar_last_checked_at: datetime | None | object = _UNSET,
        ollama_sidecar_last_model_count: int | None | object = _UNSET,
        ollama_sidecar_default_reasoning_effort: str | None | object = _UNSET,
        guest_access_enabled: bool | None = None,
        limit_warmup_staggered_idle_enabled: bool | None = None,
        request_log_retention_days: int | None = None,
        usage_history_retention_days: int | None = None,
        hourly_rollup_retention_days: int | None = None,
        clear_request_log_retention: bool = False,
        clear_usage_history_retention: bool = False,
<<<<<<< 22625a07e
        clear_hourly_rollup_retention: bool = False,
        dashboard_layout_json: str | None = None,
||||||| 84fde5a1e
=======
        # C2-3 resilience toggles (tri-state like the retention overrides)
        soft_drain_enabled: bool | None = None,
        clear_soft_drain_enabled: bool = False,
        deterministic_failover_enabled: bool | None = None,
        clear_deterministic_failover_enabled: bool = False,
        circuit_breaker_enabled: bool | None = None,
        clear_circuit_breaker_enabled: bool = False,
        # M2 background jobs (tri-state like the resilience toggles)
        auth_guardian_enabled: bool | None = None,
        clear_auth_guardian_enabled: bool = False,
        automations_scheduler_enabled: bool | None = None,
        clear_automations_scheduler_enabled: bool = False,
        rate_limit_reset_credits_refresh_enabled: bool | None = None,
        clear_rate_limit_reset_credits_refresh_enabled: bool = False,
        # M5 conversation archive (tri-state like the resilience toggles)
        conversation_archive_enabled: bool | None = None,
        clear_conversation_archive_enabled: bool = False,
        # end M5 conversation archive
        # R2 spool retention (tri-state like the C2-1 timeouts)
        http_responses_session_bridge_operation_spool_retention_seconds: float | None = None,
        clear_http_responses_session_bridge_operation_spool_retention_seconds: bool = False,
        # end R2 spool retention
        # C2-1 timeouts (tri-state: value = store, clear flag = back to NULL /
        # inherit, neither = untouched).
        upstream_connect_timeout_seconds: float | None = None,
        clear_upstream_connect_timeout_seconds: bool = False,
        proxy_request_budget_seconds: float | None = None,
        clear_proxy_request_budget_seconds: bool = False,
        compact_request_budget_seconds: float | None = None,
        clear_compact_request_budget_seconds: bool = False,
        transcription_request_budget_seconds: float | None = None,
        clear_transcription_request_budget_seconds: bool = False,
        stream_idle_timeout_seconds: float | None = None,
        clear_stream_idle_timeout_seconds: bool = False,
        proxy_downstream_websocket_idle_timeout_seconds: float | None = None,
        clear_proxy_downstream_websocket_idle_timeout_seconds: bool = False,
        sse_keepalive_interval_seconds: float | None = None,
        clear_sse_keepalive_interval_seconds: bool = False,
        # end C2-1 timeouts
        # M3 codex prewarm (tri-state like the resilience toggles)
        http_responses_session_bridge_codex_prewarm_enabled: bool | None = None,
        clear_http_responses_session_bridge_codex_prewarm_enabled: bool = False,
        # end M3 codex prewarm
        # M1 stream/bridge budgets (same tri-state contract).
        http_responses_stream_request_budget_seconds: float | None = None,
        clear_http_responses_stream_request_budget_seconds: bool = False,
        http_responses_session_bridge_request_budget_seconds: float | None = None,
        clear_http_responses_session_bridge_request_budget_seconds: bool = False,
        # end M1 stream/bridge budgets
>>>>>>> 72630bbfe
        expected_version: int | None = None,
    ) -> DashboardSettings:
        settings = await self.get_or_create()
        if expected_version is not None and settings.version != expected_version:
            # Bind the CAS to the row this UPDATE targets: with
            # DashboardSettings.version as version_id_col, commit_refresh emits
            # `UPDATE ... WHERE version = :expected`, so a writer committing in
            # between still surfaces as StaleDataError -> 409.
            raise DashboardSettingsConflictError(
                "Settings were modified since this form was loaded; reload and retry",
            )
        upstream_route_inputs_changed = (
            upstream_proxy_routing_enabled is not None
            and upstream_proxy_routing_enabled != settings.upstream_proxy_routing_enabled
        ) or (upstream_proxy_default_pool_id or None) != settings.upstream_proxy_default_pool_id
        if sticky_threads_enabled is not None:
            settings.sticky_threads_enabled = sticky_threads_enabled
        if cliproxy_capacity_routing_enabled is not None:
            settings.cliproxy_capacity_routing_enabled = cliproxy_capacity_routing_enabled
        if upstream_stream_transport is not None:
            settings.upstream_stream_transport = upstream_stream_transport
        if prohibit_fast_mode is not None:
            settings.prohibit_fast_mode = prohibit_fast_mode
        if http_downstream_transport_policy is not None:
            settings.http_downstream_transport_policy = http_downstream_transport_policy
        if clear_proxy_account_response_create_limit:
            settings.proxy_account_response_create_limit = None
        elif proxy_account_response_create_limit is not None:
            settings.proxy_account_response_create_limit = proxy_account_response_create_limit
        if clear_proxy_account_stream_limit:
            settings.proxy_account_stream_limit = None
        elif proxy_account_stream_limit is not None:
            settings.proxy_account_stream_limit = proxy_account_stream_limit
        if clear_proxy_account_stream_recovery_reserve:
            settings.proxy_account_stream_recovery_reserve = None
        elif proxy_account_stream_recovery_reserve is not None:
            settings.proxy_account_stream_recovery_reserve = proxy_account_stream_recovery_reserve
        if clear_proxy_api_key_fair_share_congestion_threshold_pct:
            settings.proxy_api_key_fair_share_congestion_threshold_pct = None
        elif proxy_api_key_fair_share_congestion_threshold_pct is not None:
            settings.proxy_api_key_fair_share_congestion_threshold_pct = (
                proxy_api_key_fair_share_congestion_threshold_pct
            )
        if clear_thread_cache_identity_mode:
            settings.thread_cache_identity_mode = None
        elif thread_cache_identity_mode is not None:
            settings.thread_cache_identity_mode = thread_cache_identity_mode
        # C2-2 routing/overload
        if clear_proxy_overload_isolation_seconds:
            settings.proxy_overload_isolation_seconds = None
        elif proxy_overload_isolation_seconds is not None:
            settings.proxy_overload_isolation_seconds = proxy_overload_isolation_seconds
        if clear_proxy_account_error_rate_weighting_enabled:
            settings.proxy_account_error_rate_weighting_enabled = None
        elif proxy_account_error_rate_weighting_enabled is not None:
            settings.proxy_account_error_rate_weighting_enabled = proxy_account_error_rate_weighting_enabled
        if clear_proxy_account_inflight_penalty_pct:
            settings.proxy_account_inflight_penalty_pct = None
        elif proxy_account_inflight_penalty_pct is not None:
            settings.proxy_account_inflight_penalty_pct = proxy_account_inflight_penalty_pct
        if clear_proxy_account_lease_token_weight:
            settings.proxy_account_lease_token_weight = None
        elif proxy_account_lease_token_weight is not None:
            settings.proxy_account_lease_token_weight = proxy_account_lease_token_weight
        if clear_proxy_account_lease_ttl_seconds:
            settings.proxy_account_lease_ttl_seconds = None
        elif proxy_account_lease_ttl_seconds is not None:
            settings.proxy_account_lease_ttl_seconds = proxy_account_lease_ttl_seconds
        # end C2-2 routing/overload
        if upstream_proxy_routing_enabled is not None:
            settings.upstream_proxy_routing_enabled = upstream_proxy_routing_enabled
        if upstream_proxy_default_pool_id is not _UNSET:
            settings.upstream_proxy_default_pool_id = upstream_proxy_default_pool_id or None
        if prefer_earlier_reset_accounts is not None:
            settings.prefer_earlier_reset_accounts = prefer_earlier_reset_accounts
        if prefer_earlier_reset_window is not None:
            settings.prefer_earlier_reset_window = prefer_earlier_reset_window
        if show_reset_credit_badges is not None:
            settings.show_reset_credit_badges = show_reset_credit_badges
        if auto_redeem_reset_credits_before_expiry is not None:
            settings.auto_redeem_reset_credits_before_expiry = auto_redeem_reset_credits_before_expiry
        if show_reset_credit_expiry_badge is not None:
            settings.show_reset_credit_expiry_badge = show_reset_credit_expiry_badge
        if routing_strategy is not None:
            settings.routing_strategy = routing_strategy
        if relative_availability_power is not None:
            settings.relative_availability_power = relative_availability_power
        if relative_availability_top_k is not None:
            settings.relative_availability_top_k = relative_availability_top_k
        if single_account_id is not None or routing_strategy == "single_account":
            settings.single_account_id = single_account_id
        if openai_cache_affinity_max_age_seconds is not None:
            settings.openai_cache_affinity_max_age_seconds = openai_cache_affinity_max_age_seconds
        if dashboard_session_ttl_seconds is not None:
            settings.dashboard_session_ttl_seconds = dashboard_session_ttl_seconds
        if http_responses_session_bridge_prompt_cache_idle_ttl_seconds is not None:
            settings.http_responses_session_bridge_prompt_cache_idle_ttl_seconds = (
                http_responses_session_bridge_prompt_cache_idle_ttl_seconds
            )
        if http_responses_session_bridge_gateway_safe_mode is not None:
            settings.http_responses_session_bridge_gateway_safe_mode = http_responses_session_bridge_gateway_safe_mode
        # M3 codex prewarm: clear flag resets to NULL (inherit the env alias /
        # code default); a non-None value is dashboard-owned.
        if clear_http_responses_session_bridge_codex_prewarm_enabled:
            settings.http_responses_session_bridge_codex_prewarm_enabled = None
        elif http_responses_session_bridge_codex_prewarm_enabled is not None:
            settings.http_responses_session_bridge_codex_prewarm_enabled = (
                http_responses_session_bridge_codex_prewarm_enabled
            )
        # end M3 codex prewarm
        if sticky_reallocation_budget_threshold_pct is not None:
            settings.sticky_reallocation_budget_threshold_pct = sticky_reallocation_budget_threshold_pct
        if sticky_reallocation_primary_budget_threshold_pct is not None:
            settings.sticky_reallocation_primary_budget_threshold_pct = sticky_reallocation_primary_budget_threshold_pct
        if sticky_reallocation_secondary_budget_threshold_pct is not None:
            settings.sticky_reallocation_secondary_budget_threshold_pct = (
                sticky_reallocation_secondary_budget_threshold_pct
            )
        if additional_quota_routing_policies_json is not None:
            settings.additional_quota_routing_policies_json = additional_quota_routing_policies_json
        if model_aliases_json is not None:
            settings.model_aliases_json = model_aliases_json
        if custom_alias_catalog_json is not None:
            settings.custom_alias_catalog_json = custom_alias_catalog_json
        if sidecar_full_model_stars_json is not None:
            settings.sidecar_full_model_stars_json = sidecar_full_model_stars_json
        if warmup_model is not None:
            settings.warmup_model = warmup_model
        if import_without_overwrite is not None:
            settings.import_without_overwrite = import_without_overwrite
        if totp_required_on_login is not None:
            settings.totp_required_on_login = totp_required_on_login
        if totp_required_for_admin_role is not None:
            settings.totp_required_for_admin_role = totp_required_for_admin_role
        if local_login_policy is not None:
            settings.local_login_policy = local_login_policy
        if api_key_auth_enabled is not None:
            settings.api_key_auth_enabled = api_key_auth_enabled
        if hide_upstream_quota_from_api_keys is not None:
            settings.hide_upstream_quota_from_api_keys = hide_upstream_quota_from_api_keys
        if limit_warmup_enabled is not None:
            settings.limit_warmup_enabled = limit_warmup_enabled
        if limit_warmup_windows is not None:
            settings.limit_warmup_windows = limit_warmup_windows
        if limit_warmup_model is not None:
            settings.limit_warmup_model = limit_warmup_model
        if limit_warmup_prompt is not None:
            settings.limit_warmup_prompt = limit_warmup_prompt
        if limit_warmup_cooldown_seconds is not None:
            settings.limit_warmup_cooldown_seconds = limit_warmup_cooldown_seconds
        if limit_warmup_exhausted_threshold_percent is not None:
            settings.limit_warmup_exhausted_threshold_percent = limit_warmup_exhausted_threshold_percent
        if limit_warmup_idle_threshold_percent is not None:
            settings.limit_warmup_idle_threshold_percent = limit_warmup_idle_threshold_percent
        if limit_warmup_min_available_percent is not None:
            settings.limit_warmup_min_available_percent = limit_warmup_min_available_percent
        if weekly_pace_working_days is not None:
            settings.weekly_pace_working_days = weekly_pace_working_days
        if weekly_pace_smoothing_minutes is not None:
            settings.weekly_pace_smoothing_minutes = weekly_pace_smoothing_minutes
        if claude_sidecar_enabled is not None:
            settings.claude_sidecar_enabled = claude_sidecar_enabled
        if claude_sidecar_base_url is not None:
            settings.claude_sidecar_base_url = claude_sidecar_base_url
        if claude_sidecar_api_key_encrypted is not _UNSET:
            settings.claude_sidecar_api_key_encrypted = claude_sidecar_api_key_encrypted
        if claude_sidecar_model_prefixes_json is not None:
            settings.claude_sidecar_model_prefixes_json = claude_sidecar_model_prefixes_json
        if claude_sidecar_full_models_json is not None:
            previous_full_models = settings.claude_sidecar_full_models_json
            settings.claude_sidecar_full_models_json = claude_sidecar_full_models_json
            await self._track_full_model_pin(
                settings.id,
                ClaudeOpus55PinOwnership,
                had_pin=_lists_full_model(previous_full_models, _CLAUDE_OPUS_5_5_PIN),
                has_pin=_lists_full_model(claude_sidecar_full_models_json, _CLAUDE_OPUS_5_5_PIN),
            )
            await self._track_full_model_pin(
                settings.id,
                ClaudeSonnet55PinOwnership,
                had_pin=_lists_full_model(previous_full_models, _CLAUDE_SONNET_5_5_PIN),
                has_pin=_lists_full_model(claude_sidecar_full_models_json, _CLAUDE_SONNET_5_5_PIN),
            )
            await self._track_full_model_pin(
                settings.id,
                ClaudeHaiku55PinOwnership,
                had_pin=_lists_full_model(previous_full_models, _CLAUDE_HAIKU_5_5_PIN),
                has_pin=_lists_full_model(claude_sidecar_full_models_json, _CLAUDE_HAIKU_5_5_PIN),
            )
        if claude_sidecar_connect_timeout_seconds is not None:
            settings.claude_sidecar_connect_timeout_seconds = claude_sidecar_connect_timeout_seconds
        if claude_sidecar_request_timeout_seconds is not None:
            settings.claude_sidecar_request_timeout_seconds = claude_sidecar_request_timeout_seconds
        if claude_sidecar_models_cache_ttl_seconds is not None:
            settings.claude_sidecar_models_cache_ttl_seconds = claude_sidecar_models_cache_ttl_seconds
        if claude_sidecar_last_health_status is not _UNSET:
            settings.claude_sidecar_last_health_status = claude_sidecar_last_health_status
        if claude_sidecar_last_health_message is not _UNSET:
            settings.claude_sidecar_last_health_message = claude_sidecar_last_health_message
        if claude_sidecar_last_checked_at is not _UNSET:
            settings.claude_sidecar_last_checked_at = claude_sidecar_last_checked_at
        if claude_sidecar_last_model_count is not _UNSET:
            settings.claude_sidecar_last_model_count = claude_sidecar_last_model_count
        if claude_sidecar_management_key_encrypted is not _UNSET:
            settings.claude_sidecar_management_key_encrypted = claude_sidecar_management_key_encrypted
        if claude_sidecar_quota_poll_interval_seconds is not None:
            settings.claude_sidecar_quota_poll_interval_seconds = claude_sidecar_quota_poll_interval_seconds
        if claude_sidecar_quota_state_json is not _UNSET:
            settings.claude_sidecar_quota_state_json = claude_sidecar_quota_state_json
        if claude_sidecar_quota_checked_at is not _UNSET:
            settings.claude_sidecar_quota_checked_at = claude_sidecar_quota_checked_at
        if claude_sidecar_auth_plans_json is not None:
            settings.claude_sidecar_auth_plans_json = claude_sidecar_auth_plans_json
        if claude_sidecar_usage_poll_interval_seconds is not None:
            settings.claude_sidecar_usage_poll_interval_seconds = claude_sidecar_usage_poll_interval_seconds
        if claude_sidecar_usage_queue_batch_size is not None:
            settings.claude_sidecar_usage_queue_batch_size = claude_sidecar_usage_queue_batch_size
        if claude_sidecar_usage_collection_enabled is not None:
            settings.claude_sidecar_usage_collection_enabled = claude_sidecar_usage_collection_enabled
        if claude_sidecar_default_reasoning_effort is not _UNSET:
            settings.claude_sidecar_default_reasoning_effort = claude_sidecar_default_reasoning_effort
        if openrouter_sidecar_enabled is not None:
            settings.openrouter_sidecar_enabled = openrouter_sidecar_enabled
        if openrouter_sidecar_base_url is not None:
            settings.openrouter_sidecar_base_url = openrouter_sidecar_base_url
        if openrouter_sidecar_api_key_encrypted is not _UNSET:
            settings.openrouter_sidecar_api_key_encrypted = openrouter_sidecar_api_key_encrypted
        if openrouter_sidecar_model_prefixes_json is not None:
            settings.openrouter_sidecar_model_prefixes_json = openrouter_sidecar_model_prefixes_json
        if openrouter_sidecar_full_models_json is not None:
            settings.openrouter_sidecar_full_models_json = openrouter_sidecar_full_models_json
        if openrouter_sidecar_connect_timeout_seconds is not None:
            settings.openrouter_sidecar_connect_timeout_seconds = openrouter_sidecar_connect_timeout_seconds
        if openrouter_sidecar_request_timeout_seconds is not None:
            settings.openrouter_sidecar_request_timeout_seconds = openrouter_sidecar_request_timeout_seconds
        if openrouter_sidecar_models_cache_ttl_seconds is not None:
            settings.openrouter_sidecar_models_cache_ttl_seconds = openrouter_sidecar_models_cache_ttl_seconds
        if openrouter_sidecar_last_health_status is not _UNSET:
            settings.openrouter_sidecar_last_health_status = openrouter_sidecar_last_health_status
        if openrouter_sidecar_last_health_message is not _UNSET:
            settings.openrouter_sidecar_last_health_message = openrouter_sidecar_last_health_message
        if openrouter_sidecar_last_checked_at is not _UNSET:
            settings.openrouter_sidecar_last_checked_at = openrouter_sidecar_last_checked_at
        if openrouter_sidecar_last_model_count is not _UNSET:
            settings.openrouter_sidecar_last_model_count = openrouter_sidecar_last_model_count
        if openrouter_sidecar_default_reasoning_effort is not _UNSET:
            settings.openrouter_sidecar_default_reasoning_effort = openrouter_sidecar_default_reasoning_effort
        if openai_compat_endpoints_json is not None:
            settings.openai_compat_endpoints_json = openai_compat_endpoints_json
        if orcarouter_sidecar_enabled is not None:
            settings.orcarouter_sidecar_enabled = orcarouter_sidecar_enabled
        if orcarouter_sidecar_base_url is not None:
            settings.orcarouter_sidecar_base_url = orcarouter_sidecar_base_url
        if orcarouter_sidecar_api_key_encrypted is not _UNSET:
            settings.orcarouter_sidecar_api_key_encrypted = orcarouter_sidecar_api_key_encrypted
        if orcarouter_sidecar_model_prefixes_json is not None:
            settings.orcarouter_sidecar_model_prefixes_json = orcarouter_sidecar_model_prefixes_json
        if orcarouter_sidecar_full_models_json is not None:
            settings.orcarouter_sidecar_full_models_json = orcarouter_sidecar_full_models_json
        if orcarouter_sidecar_connect_timeout_seconds is not None:
            settings.orcarouter_sidecar_connect_timeout_seconds = orcarouter_sidecar_connect_timeout_seconds
        if orcarouter_sidecar_request_timeout_seconds is not None:
            settings.orcarouter_sidecar_request_timeout_seconds = orcarouter_sidecar_request_timeout_seconds
        if orcarouter_sidecar_models_cache_ttl_seconds is not None:
            settings.orcarouter_sidecar_models_cache_ttl_seconds = orcarouter_sidecar_models_cache_ttl_seconds
        if orcarouter_sidecar_last_health_status is not _UNSET:
            settings.orcarouter_sidecar_last_health_status = orcarouter_sidecar_last_health_status
        if orcarouter_sidecar_last_health_message is not _UNSET:
            settings.orcarouter_sidecar_last_health_message = orcarouter_sidecar_last_health_message
        if orcarouter_sidecar_last_checked_at is not _UNSET:
            settings.orcarouter_sidecar_last_checked_at = orcarouter_sidecar_last_checked_at
        if orcarouter_sidecar_last_model_count is not _UNSET:
            settings.orcarouter_sidecar_last_model_count = orcarouter_sidecar_last_model_count
        if orcarouter_sidecar_default_reasoning_effort is not _UNSET:
            settings.orcarouter_sidecar_default_reasoning_effort = orcarouter_sidecar_default_reasoning_effort
        if opencode_go_sidecar_enabled is not None:
            settings.opencode_go_sidecar_enabled = opencode_go_sidecar_enabled
        if opencode_go_sidecar_base_url is not None:
            settings.opencode_go_sidecar_base_url = opencode_go_sidecar_base_url
        if opencode_go_sidecar_api_key_encrypted is not _UNSET:
            settings.opencode_go_sidecar_api_key_encrypted = opencode_go_sidecar_api_key_encrypted
        if opencode_go_sidecar_model_prefixes_json is not None:
            settings.opencode_go_sidecar_model_prefixes_json = opencode_go_sidecar_model_prefixes_json
        if opencode_go_sidecar_full_models_json is not None:
            settings.opencode_go_sidecar_full_models_json = opencode_go_sidecar_full_models_json
        if opencode_go_sidecar_connect_timeout_seconds is not None:
            settings.opencode_go_sidecar_connect_timeout_seconds = opencode_go_sidecar_connect_timeout_seconds
        if opencode_go_sidecar_request_timeout_seconds is not None:
            settings.opencode_go_sidecar_request_timeout_seconds = opencode_go_sidecar_request_timeout_seconds
        if opencode_go_sidecar_models_cache_ttl_seconds is not None:
            settings.opencode_go_sidecar_models_cache_ttl_seconds = opencode_go_sidecar_models_cache_ttl_seconds
        if omniroute_sidecar_enabled is not None:
            settings.omniroute_sidecar_enabled = omniroute_sidecar_enabled
        if omniroute_sidecar_base_url is not None:
            settings.omniroute_sidecar_base_url = omniroute_sidecar_base_url
        if omniroute_sidecar_api_key_encrypted is not _UNSET:
            settings.omniroute_sidecar_api_key_encrypted = omniroute_sidecar_api_key_encrypted
        if omniroute_sidecar_selected_models_json is not None:
            settings.omniroute_sidecar_selected_models_json = omniroute_sidecar_selected_models_json
        if omniroute_sidecar_prefixes_json is not None:
            settings.omniroute_sidecar_prefixes_json = omniroute_sidecar_prefixes_json
        if omniroute_sidecar_connect_timeout_seconds is not None:
            settings.omniroute_sidecar_connect_timeout_seconds = omniroute_sidecar_connect_timeout_seconds
        if omniroute_sidecar_request_timeout_seconds is not None:
            settings.omniroute_sidecar_request_timeout_seconds = omniroute_sidecar_request_timeout_seconds
        if omniroute_sidecar_models_cache_ttl_seconds is not None:
            settings.omniroute_sidecar_models_cache_ttl_seconds = omniroute_sidecar_models_cache_ttl_seconds
        if omniroute_sidecar_last_health_status is not _UNSET:
            settings.omniroute_sidecar_last_health_status = omniroute_sidecar_last_health_status
        if omniroute_sidecar_last_health_message is not _UNSET:
            settings.omniroute_sidecar_last_health_message = omniroute_sidecar_last_health_message
        if omniroute_sidecar_last_checked_at is not _UNSET:
            settings.omniroute_sidecar_last_checked_at = omniroute_sidecar_last_checked_at
        if omniroute_sidecar_last_model_count is not _UNSET:
            settings.omniroute_sidecar_last_model_count = omniroute_sidecar_last_model_count
        if omniroute_sidecar_default_reasoning_effort is not _UNSET:
            settings.omniroute_sidecar_default_reasoning_effort = omniroute_sidecar_default_reasoning_effort
        if ollama_sidecar_enabled is not None:
            settings.ollama_sidecar_enabled = ollama_sidecar_enabled
        if ollama_sidecar_base_url is not None:
            settings.ollama_sidecar_base_url = ollama_sidecar_base_url
        if ollama_sidecar_api_key_encrypted is not _UNSET:
            settings.ollama_sidecar_api_key_encrypted = ollama_sidecar_api_key_encrypted
        if ollama_sidecar_model_prefixes_json is not None:
            settings.ollama_sidecar_model_prefixes_json = ollama_sidecar_model_prefixes_json
        if ollama_sidecar_full_models_json is not None:
            settings.ollama_sidecar_full_models_json = ollama_sidecar_full_models_json
        if ollama_sidecar_connect_timeout_seconds is not None:
            settings.ollama_sidecar_connect_timeout_seconds = ollama_sidecar_connect_timeout_seconds
        if ollama_sidecar_request_timeout_seconds is not None:
            settings.ollama_sidecar_request_timeout_seconds = ollama_sidecar_request_timeout_seconds
        if ollama_sidecar_models_cache_ttl_seconds is not None:
            settings.ollama_sidecar_models_cache_ttl_seconds = ollama_sidecar_models_cache_ttl_seconds
        if ollama_sidecar_last_health_status is not _UNSET:
            settings.ollama_sidecar_last_health_status = ollama_sidecar_last_health_status
        if ollama_sidecar_last_health_message is not _UNSET:
            settings.ollama_sidecar_last_health_message = ollama_sidecar_last_health_message
        if ollama_sidecar_last_checked_at is not _UNSET:
            settings.ollama_sidecar_last_checked_at = ollama_sidecar_last_checked_at
        if ollama_sidecar_last_model_count is not _UNSET:
            settings.ollama_sidecar_last_model_count = ollama_sidecar_last_model_count
        if ollama_sidecar_default_reasoning_effort is not _UNSET:
            settings.ollama_sidecar_default_reasoning_effort = ollama_sidecar_default_reasoning_effort
        if guest_access_enabled is not None:
            if settings.guest_access_enabled and not guest_access_enabled:
                # Disabling guest access must not leave already-issued guest
                # cookies valid for when it is re-enabled later.
                settings.guest_session_generation += 1
            settings.guest_access_enabled = guest_access_enabled
        if limit_warmup_staggered_idle_enabled is not None:
            settings.limit_warmup_staggered_idle_enabled = limit_warmup_staggered_idle_enabled
        # Retention overrides are tri-state: a clear flag resets the column to
        # NULL (not configured = retention disabled); a non-None value stores an
        # override; neither leaves the stored value untouched.
        if clear_request_log_retention:
            settings.request_log_retention_days = None
        elif request_log_retention_days is not None:
            settings.request_log_retention_days = request_log_retention_days
        if clear_usage_history_retention:
            settings.usage_history_retention_days = None
        elif usage_history_retention_days is not None:
            settings.usage_history_retention_days = usage_history_retention_days
<<<<<<< 22625a07e
        if clear_hourly_rollup_retention:
            settings.hourly_rollup_retention_days = None
        elif hourly_rollup_retention_days is not None:
            settings.hourly_rollup_retention_days = hourly_rollup_retention_days
        if dashboard_layout_json is not None:
            settings.dashboard_layout_json = dashboard_layout_json
||||||| 84fde5a1e
=======
        # C2-3 resilience toggles: clear flag resets to NULL (inherit the env
        # alias / code default); a non-None value is dashboard-owned.
        if clear_soft_drain_enabled:
            settings.soft_drain_enabled = None
        elif soft_drain_enabled is not None:
            settings.soft_drain_enabled = soft_drain_enabled
        if clear_deterministic_failover_enabled:
            settings.deterministic_failover_enabled = None
        elif deterministic_failover_enabled is not None:
            settings.deterministic_failover_enabled = deterministic_failover_enabled
        if clear_circuit_breaker_enabled:
            settings.circuit_breaker_enabled = None
        elif circuit_breaker_enabled is not None:
            settings.circuit_breaker_enabled = circuit_breaker_enabled
        # M2 background jobs: clear flag resets to NULL (inherit the env alias
        # / code default); a non-None value is dashboard-owned.
        for column_name, value, clear in (
            ("auth_guardian_enabled", auth_guardian_enabled, clear_auth_guardian_enabled),
            ("automations_scheduler_enabled", automations_scheduler_enabled, clear_automations_scheduler_enabled),
            (
                "rate_limit_reset_credits_refresh_enabled",
                rate_limit_reset_credits_refresh_enabled,
                clear_rate_limit_reset_credits_refresh_enabled,
            ),
        ):
            if clear:
                setattr(settings, column_name, None)
            elif value is not None:
                setattr(settings, column_name, value)
        # end M2 background jobs
        # M5 conversation archive: clear flag resets to NULL (inherit the env
        # alias / code default); a non-None value is dashboard-owned.
        if clear_conversation_archive_enabled:
            settings.conversation_archive_enabled = None
        elif conversation_archive_enabled is not None:
            settings.conversation_archive_enabled = conversation_archive_enabled
        # end M5 conversation archive
        # R2 spool retention: clear flag resets to NULL (inherit the env alias
        # / code default); a non-None value is dashboard-owned.
        if clear_http_responses_session_bridge_operation_spool_retention_seconds:
            settings.http_responses_session_bridge_operation_spool_retention_seconds = None
        elif http_responses_session_bridge_operation_spool_retention_seconds is not None:
            settings.http_responses_session_bridge_operation_spool_retention_seconds = (
                http_responses_session_bridge_operation_spool_retention_seconds
            )
        # end R2 spool retention
        # C2-1 timeouts
        for column_name, value, clear in (
            (
                "upstream_connect_timeout_seconds",
                upstream_connect_timeout_seconds,
                clear_upstream_connect_timeout_seconds,
            ),
            ("proxy_request_budget_seconds", proxy_request_budget_seconds, clear_proxy_request_budget_seconds),
            ("compact_request_budget_seconds", compact_request_budget_seconds, clear_compact_request_budget_seconds),
            (
                "transcription_request_budget_seconds",
                transcription_request_budget_seconds,
                clear_transcription_request_budget_seconds,
            ),
            ("stream_idle_timeout_seconds", stream_idle_timeout_seconds, clear_stream_idle_timeout_seconds),
            (
                "proxy_downstream_websocket_idle_timeout_seconds",
                proxy_downstream_websocket_idle_timeout_seconds,
                clear_proxy_downstream_websocket_idle_timeout_seconds,
            ),
            ("sse_keepalive_interval_seconds", sse_keepalive_interval_seconds, clear_sse_keepalive_interval_seconds),
            # M1 stream/bridge budgets
            (
                "http_responses_stream_request_budget_seconds",
                http_responses_stream_request_budget_seconds,
                clear_http_responses_stream_request_budget_seconds,
            ),
            (
                "http_responses_session_bridge_request_budget_seconds",
                http_responses_session_bridge_request_budget_seconds,
                clear_http_responses_session_bridge_request_budget_seconds,
            ),
            # end M1 stream/bridge budgets
        ):
            if clear:
                setattr(settings, column_name, None)
            elif value is not None:
                setattr(settings, column_name, value)
        # end C2-1 timeouts
>>>>>>> 72630bbfe
        # Force the optimistic-version CAS to run even when the payload makes no
        # net change. `version_id_col` only raises `StaleDataError` when the
        # flush emits an ORM UPDATE; a full-row save that assigns values all
        # equal to this (possibly stale) session's row would otherwise flush
        # nothing, commit silently, and refresh over a concurrent writer's
        # values without the required 409. Flagging a column dirty guarantees an
        # `UPDATE ... SET version = version + 1 WHERE version = :expected`, so a
        # stale no-op save still surfaces the conflict.
        flag_modified(settings, "sticky_threads_enabled")
        # The route cache must be cleared synchronously between the commit and
        # the refresh await: the committed row is visible to concurrent
        # requests as soon as the commit returns, and any await before the
        # clear would let them resolve from the stale per-account route cache
        # (e.g. cached direct egress immediately after routing was enabled).
        await self.commit_refresh(
            settings,
            on_committed=get_upstream_route_cache().clear if upstream_route_inputs_changed else None,
        )
        return settings

    async def _track_full_model_pin(
        self,
        settings_id: int,
        ownership: _PinOwnership,
        *,
        had_pin: bool,
        has_pin: bool,
    ) -> None:
        """Keep a pin-ownership row true to who placed that pin.

        Revisions 20260923_000000 and 20260928_000000 each read their ownership
        row two ways. Upgrade, which a legacy-revision remap can replay, skips
        owned rows. Downgrade removes that revision's id from owned rows.

        Only a save that removes or adds the pin changes the row:

        - Removing it keeps (or adds) the row, so a replay does not pin it
          again. Downgrade has no pin to remove there.
        - Adding it back drops the row, so downgrade leaves the operator's
          pin. A replay skips it because the pin is present.

        No autoflush: the settings UPDATE and its version check must flush in
        commit_refresh, which turns a stale save into a 409. A conflict there
        rolls these statements back too.
        """
        if has_pin == had_pin:
            return
        with self._session.no_autoflush:
            if has_pin:
                await self._session.execute(delete(ownership).where(ownership.settings_id == settings_id))
                return
            dialect = self._session.get_bind().dialect.name
            insert_fn = postgresql_insert if dialect == "postgresql" else sqlite_insert
            await self._session.execute(
                insert_fn(ownership)
                .values(settings_id=settings_id)
                .on_conflict_do_nothing(index_elements=[ownership.settings_id])
            )

    async def commit_refresh(
        self, settings: DashboardSettings, *, on_committed: Callable[[], None] | None = None
    ) -> None:
        try:
            await self._session.commit()
        except StaleDataError as exc:
            # The optimistic version check (DashboardSettings.version) matched
            # zero rows: another writer (replica or request) committed first.
            await self._session.rollback()
            raise DashboardSettingsConflictError() from exc
        if on_committed is not None:
            # Runs synchronously between the commit and the refresh await so
            # concurrent requests cannot observe the committed row alongside
            # stale state the hook is meant to reset.
            on_committed()
        await self._session.refresh(settings)


# M4 model catalogue: dashboard rows of the per-model context window overrides.
_UPSERT_INSERT_FNS = {"postgresql": pg_insert, "sqlite": sqlite_insert}


class ModelContextWindowOverridesRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_all(self) -> list[ModelContextWindowOverride]:
        result = await self._session.execute(
            select(ModelContextWindowOverride).order_by(ModelContextWindowOverride.slug.asc())
        )
        return list(result.scalars().all())

    async def by_slug(self) -> dict[str, int]:
        """``slug -> context_window`` for every dashboard row."""
        return {row.slug: row.context_window for row in await self.list_all()}

    async def upsert(self, slug: str, context_window: int) -> None:
        """Create or replace the row for ``slug`` in one statement.

        A read-then-insert would let two concurrent creates of the same new slug
        both miss and one fail the primary key, turning a documented
        create-or-replace into a 500. ``updated_at`` is set explicitly because
        the ORM ``onupdate`` does not fire for a Core insert.
        """
        dialect = self._session.get_bind().dialect.name
        insert_fn = _UPSERT_INSERT_FNS.get(dialect)
        if insert_fn is None:
            raise RuntimeError(f"model_context_window_overrides upsert unsupported for dialect={dialect!r}")
        statement = insert_fn(ModelContextWindowOverride).values(slug=slug, context_window=context_window)
        await self._session.execute(
            statement.on_conflict_do_update(
                index_elements=[ModelContextWindowOverride.slug],
                set_={"context_window": context_window, "updated_at": func.now()},
            )
        )
        await self._session.commit()

    async def delete(self, slug: str) -> bool:
        row = await self._session.get(ModelContextWindowOverride, slug)
        if row is None:
            return False
        await self._session.delete(row)
        await self._session.commit()
        return True


# end M4 model catalogue
