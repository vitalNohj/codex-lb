"""Human labels for the CLIProxyAPI credential that served a request.

Request logs record the dispatch-time ``auth_index``, an opaque hash. The
dashboard shows the account behind it instead: the OAuth account's email (or
its auth-file name) from the stored quota snapshot, or the API-key account's
name from CLIProxyAPI's API-key config.

The snapshot is local, so it costs no network call. The API-key config is one
management read, made only when a page has an ``auth_index`` the snapshot
cannot name, and cached briefly (failures too) so paging through the log does
not call CLIProxyAPI per page.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Iterable, Mapping

from app.core.clients.claude_sidecar import ClaudeSidecarClient
from app.db.models import DashboardSettings
from app.modules.claude_sidecar.capacity_hold import StoredSnapshotReader
from app.modules.claude_sidecar.quota import SidecarQuotaSnapshot
from app.modules.cliproxy_accounts.api_keys import ApiKeyRouteRow, list_routing_api_keys

logger = logging.getLogger(__name__)

_API_KEY_LABEL_TTL_SECONDS = 60.0
_API_KEY_LABEL_TIMEOUT_SECONDS = 3.0
_KIND_LABELS = {
    "openai-compatibility": "OpenAI-compatible",
    "claude": "Claude",
    "gemini": "Gemini",
    "codex": "Codex",
    "xai": "xAI",
}

ApiKeyRowsLoader = Callable[[DashboardSettings], Awaitable[Iterable[ApiKeyRouteRow]]]


def snapshot_identity_labels(snapshot: SidecarQuotaSnapshot | None) -> dict[str, str]:
    """``auth_index`` -> email (or auth-file name) for every snapshot account."""

    if snapshot is None:
        return {}
    labels: dict[str, str] = {}
    for account in snapshot.accounts:
        auth_index = _text(account.auth_index)
        label = _text(account.email) or _text(account.name)
        if auth_index and label:
            labels.setdefault(auth_index, label)
    return labels


def api_key_identity_labels(rows: Iterable[ApiKeyRouteRow]) -> dict[str, str]:
    """``auth_index`` -> display name for every API-key account.

    A row is keyed by CLIProxyAPI's reported ``auth_index`` and by its routing
    identity, which is the same digest computed locally when the report is
    missing, so a log written either way resolves.
    """

    labels: dict[str, str] = {}
    for row in rows:
        label = api_key_display_name(row)
        for key in (_text(row.auth_index), _text(row.route_identity)):
            if key:
                labels.setdefault(key, label)
    return labels


def api_key_display_name(row: ApiKeyRouteRow) -> str:
    """The name the CLIProxyAPI accounts panel shows for an API-key account."""

    # Routing rows carry the provider name, the ``<group>#<n>`` of a keyed
    # group, or ``<kind>:<index>`` when the account has neither.
    name = _text(row.name)
    if name and name != f"{row.kind}:{row.index}":
        return name
    return f"{_KIND_LABELS.get(row.kind, row.kind)} API key {row.index + 1}"


class CliproxyIdentityResolver:
    """Resolve ``auth_index`` values to account labels for a page of logs."""

    def __init__(
        self,
        *,
        load_api_key_rows: ApiKeyRowsLoader | None = None,
        ttl_seconds: float = _API_KEY_LABEL_TTL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._snapshots = StoredSnapshotReader()
        self._load_api_key_rows = load_api_key_rows or _load_api_key_rows
        self._ttl_seconds = ttl_seconds
        self._clock = clock
        self._api_key_labels: tuple[float, Mapping[str, str]] | None = None
        self._lock = asyncio.Lock()

    async def labels_for(
        self,
        settings: DashboardSettings | None,
        auth_indexes: Iterable[str | None],
    ) -> dict[str, str]:
        wanted = {text for value in auth_indexes if (text := _text(value))}
        if not wanted or settings is None:
            return {}
        snapshot_labels = snapshot_identity_labels(self._snapshots.read(settings.claude_sidecar_quota_state_json))
        resolved = {key: snapshot_labels[key] for key in wanted if key in snapshot_labels}
        missing = wanted - resolved.keys()
        if missing and _management_configured(settings):
            api_key_labels = await self._cached_api_key_labels(settings)
            resolved.update({key: api_key_labels[key] for key in missing if key in api_key_labels})
        return resolved

    def clear(self) -> None:
        self._api_key_labels = None

    async def _cached_api_key_labels(self, settings: DashboardSettings) -> Mapping[str, str]:
        cached = self._fresh_api_key_labels()
        if cached is not None:
            return cached
        async with self._lock:
            cached = self._fresh_api_key_labels()
            if cached is not None:
                return cached
            labels: Mapping[str, str]
            try:
                rows = await asyncio.wait_for(self._load_api_key_rows(settings), _API_KEY_LABEL_TIMEOUT_SECONDS)
                labels = api_key_identity_labels(rows)
            except Exception:
                logger.info("cliproxy api-key labels unavailable for request logs", exc_info=True)
                labels = {}
            self._api_key_labels = (self._clock(), labels)
            return labels

    def _fresh_api_key_labels(self) -> Mapping[str, str] | None:
        cached = self._api_key_labels
        if cached is None or self._clock() - cached[0] >= self._ttl_seconds:
            return None
        return cached[1]


async def _load_api_key_rows(settings: DashboardSettings) -> list[ApiKeyRouteRow]:
    # Imported here: the dispatch module imports the request-log repository.
    from app.modules.proxy.claude_sidecar_dispatch import sidecar_config_from_settings

    return await list_routing_api_keys(ClaudeSidecarClient(sidecar_config_from_settings(settings)))


def _management_configured(settings: DashboardSettings) -> bool:
    return bool((settings.claude_sidecar_base_url or "").strip() and settings.claude_sidecar_management_key_encrypted)


def _text(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


_RESOLVER = CliproxyIdentityResolver()


def get_cliproxy_identity_resolver() -> CliproxyIdentityResolver:
    return _RESOLVER
