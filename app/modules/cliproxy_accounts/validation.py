"""Checks for CLIProxyAPI credential field edits.

A credential prefix has to be a short slug such as ``acct1``. It must not
match another credential or a sidecar routing prefix: those prefixes already
decide which integration receives ``prefix/model`` requests. This module does
not change that routing.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from app.core.config.product_capabilities import omniroute_enabled
from app.core.exceptions import DashboardBadRequestError
from app.db.models import DashboardSettings
from app.modules.claude_sidecar.excluded_models import MAX_PATTERN_LENGTH, MAX_PATTERNS, normalize_excluded_models
from app.modules.claude_sidecar.quota import SidecarAuthQuota
from app.modules.openai_compat.endpoints import parse_openai_compat_endpoints
from app.modules.proxy.sidecar_routing import parse_sidecar_prefixes, prefix_variants

_ACCOUNT_PREFIX = re.compile(r"^acct[1-9][0-9]{0,5}$")
MAX_WEIGHT = 1_000_000
MAX_PRIORITY = 1_000_000


@dataclass(frozen=True, slots=True)
class CredentialFieldChange:
    prefix: str | None = None
    weight: int | None = None
    priority: int | None = None
    excluded_models: tuple[str, ...] | None = None
    update_prefix: bool = False
    update_weight: bool = False
    update_priority: bool = False
    update_excluded_models: bool = False
    confirm: bool = False

    @property
    def changed_fields(self) -> tuple[str, ...]:
        names: list[str] = []
        if self.update_prefix:
            names.append("prefix")
        if self.update_weight:
            names.append("weight")
        if self.update_priority:
            names.append("priority")
        if self.update_excluded_models:
            names.append("excluded_models")
        return tuple(names)

    def is_empty(self) -> bool:
        return not self.changed_fields


def normalized_tag(value: str | None) -> str:
    """Compare tags without surrounding space or case differences."""

    return (value or "").strip().lower()


def tag_is_changing(current: str | None, requested: str | None) -> bool:
    """A tag edit is the risky change that needs a confirmation."""

    return normalized_tag(current) != normalized_tag(requested)


def disabling_last_enabled_account(
    accounts: Sequence[SidecarAuthQuota],
    *,
    name: str,
    disabled: bool,
) -> bool:
    """True when this write would leave no enabled CLIProxyAPI account."""

    if not disabled:
        return False
    target = next((account for account in accounts if account.name == name), None)
    if target is None or target.disabled:
        return False
    return sum(1 for account in accounts if not account.disabled) <= 1


def normalize_credential_prefix(raw: str) -> str:
    trimmed = raw.strip().lower()
    if not trimmed:
        raise DashboardBadRequestError("Prefix cannot be empty")
    if "/" in trimmed or "\\" in trimmed or any(char.isspace() for char in trimmed):
        raise DashboardBadRequestError("Prefix must be a single segment such as acct1")
    if _ACCOUNT_PREFIX.fullmatch(trimmed) is None:
        raise DashboardBadRequestError("Prefix must be a short slug such as acct1 or acct2")
    return trimmed


def validate_weight(weight: int) -> int:
    if isinstance(weight, bool) or not isinstance(weight, int):
        raise DashboardBadRequestError("Weight must be an integer")
    if weight < 0 or weight > MAX_WEIGHT:
        raise DashboardBadRequestError(f"Weight must be between 0 and {MAX_WEIGHT}")
    return weight


def validate_priority(priority: int) -> int:
    if isinstance(priority, bool) or not isinstance(priority, int):
        raise DashboardBadRequestError("Priority must be an integer")
    if priority < -MAX_PRIORITY or priority > MAX_PRIORITY:
        raise DashboardBadRequestError(f"Priority must be between -{MAX_PRIORITY} and {MAX_PRIORITY}")
    return priority


def validate_excluded_models(patterns: Sequence[str]) -> tuple[str, ...]:
    raw = list(patterns)
    normalized = normalize_excluded_models(raw)
    if normalized != raw:
        raise DashboardBadRequestError(
            "Excluded models must already be trimmed patterns without commas, "
            f"at most {MAX_PATTERNS} entries of {MAX_PATTERN_LENGTH} characters"
        )
    return tuple(normalized)


def prefix_keys(value: str) -> tuple[str, ...]:
    """Return the routing keys one prefix occupies, including ``-``/``_`` twins."""

    trimmed = value.strip().lower().strip("/")
    if not trimmed or "/" in trimmed:
        return ()
    return prefix_variants(trimmed)


def routing_prefix_owners(settings: DashboardSettings) -> dict[str, str]:
    """Map each live sidecar routing prefix variant to the integration that owns it."""

    columns: list[tuple[str, str | None]] = [
        ("CLIProxyAPI", settings.claude_sidecar_model_prefixes_json),
        ("OpenRouter", settings.openrouter_sidecar_model_prefixes_json),
        ("OrcaRouter", settings.orcarouter_sidecar_model_prefixes_json),
        ("OpenCode Go", settings.opencode_go_sidecar_model_prefixes_json),
        ("Ollama", settings.ollama_sidecar_model_prefixes_json),
    ]
    if omniroute_enabled():
        columns.append(("OmniRoute", settings.omniroute_sidecar_prefixes_json))
    owners: dict[str, str] = {}
    for owner, raw in columns:
        for prefix in parse_sidecar_prefixes(raw):
            for variant in prefix_keys(prefix.prefix):
                owners.setdefault(variant, owner)
    for endpoint in parse_openai_compat_endpoints(settings.openai_compat_endpoints_json):
        for prefix in endpoint.prefixes:
            for variant in prefix_keys(prefix.prefix):
                owners.setdefault(variant, endpoint.name)
    return owners


def effective_prefixes(accounts: Sequence[SidecarAuthQuota], stored: Mapping[str, str]) -> dict[str, str]:
    """Return the prefix each credential occupies.

    A stored registry value wins over a prefix CLIProxyAPI happened to return.
    A stored prefix whose credential is missing from the current auth-file list
    still occupies its slug, so a later assignment cannot reuse it.
    """

    resolved: dict[str, str] = {}
    live = {account.name for account in accounts}
    for account in accounts:
        stored_prefix = stored.get(account.name)
        prefix = stored_prefix if stored_prefix else account.prefix
        if prefix and prefix.strip():
            resolved[account.name] = prefix.strip()
    for name, prefix in stored.items():
        if name in live or not prefix or not prefix.strip():
            continue
        resolved[name] = prefix.strip()
    return resolved


def prefix_conflict_message(
    prefix: str,
    *,
    credential_name: str,
    effective: Mapping[str, str],
    routing_owners: Mapping[str, str],
) -> str | None:
    occupied: dict[str, str] = {}
    for name, current in effective.items():
        if name == credential_name:
            continue
        for key in prefix_keys(current):
            occupied.setdefault(key, name)
    for variant in prefix_keys(prefix):
        owner = routing_owners.get(variant)
        if owner is not None:
            return f"Prefix {prefix} clashes with the {owner} routing prefix"
        holder = occupied.get(variant)
        if holder is not None:
            return f"Prefix {prefix} is already assigned to {holder}"
    return None
