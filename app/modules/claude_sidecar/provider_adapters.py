from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from app.core.types import JsonValue

QuotaWindow = Literal["five_hour", "weekly"]


@dataclass(frozen=True, slots=True)
class SidecarProviderAdapter:
    provider: str
    label: str
    quota_windows: tuple[QuotaWindow, ...]
    supports_manual_plan: bool
    supports_anthropic_oauth: bool = False


CLAUDE_ADAPTER = SidecarProviderAdapter(
    provider="claude",
    label="Claude",
    quota_windows=("five_hour", "weekly"),
    supports_manual_plan=True,
    supports_anthropic_oauth=True,
)
XAI_ADAPTER = SidecarProviderAdapter(
    provider="xai",
    label="Grok",
    quota_windows=(),
    supports_manual_plan=True,
)
DEFAULT_ADAPTER = SidecarProviderAdapter(
    provider="unknown",
    label="CLIProxyAPI",
    quota_windows=(),
    supports_manual_plan=True,
)

_ADAPTERS = {
    CLAUDE_ADAPTER.provider: CLAUDE_ADAPTER,
    XAI_ADAPTER.provider: XAI_ADAPTER,
}
_CLAUDE_ALIASES = frozenset({"claude", "anthropic"})
_XAI_ALIASES = frozenset({"xai", "x.ai", "grok"})


def normalize_provider(value: str | None) -> str:
    normalized = value.strip().lower() if isinstance(value, str) else ""
    if normalized in _CLAUDE_ALIASES:
        return "claude"
    if normalized in _XAI_ALIASES:
        return "xai"
    return "unknown"


def adapter_for_provider(provider: str | None) -> SidecarProviderAdapter:
    return _ADAPTERS.get(normalize_provider(provider), DEFAULT_ADAPTER)


def adapter_for_auth_entry(entry: Mapping[str, JsonValue]) -> SidecarProviderAdapter:
    for field in ("provider", "type", "account_type"):
        value = entry.get(field)
        normalized = normalize_provider(value if isinstance(value, str) else None)
        if normalized != "unknown":
            return _ADAPTERS[normalized]
    return DEFAULT_ADAPTER


def manual_plan_budget_error(
    provider: str | None,
    primary_token_budget: int | None,
    secondary_token_budget: int | None,
) -> str | None:
    adapter = adapter_for_provider(provider)
    if adapter.provider == "claude":
        if primary_token_budget is None or secondary_token_budget is None:
            return "custom Claude auth plan requires both token budgets"
        return None
    if primary_token_budget is None and secondary_token_budget is None:
        return "non-Claude custom auth plan requires at least one token budget"
    if adapter.quota_windows:
        if primary_token_budget is not None and "five_hour" not in adapter.quota_windows:
            return "provider does not declare a five-hour quota window"
        if secondary_token_budget is not None and "weekly" not in adapter.quota_windows:
            return "provider does not declare a weekly quota window"
    return None


def quota_windows_for_plan(
    provider: str | None,
    primary_token_budget: int | None,
    secondary_token_budget: int | None,
) -> tuple[QuotaWindow, ...]:
    adapter = adapter_for_provider(provider)
    windows = list(adapter.quota_windows)
    if not adapter.supports_manual_plan or windows:
        return tuple(windows)
    if primary_token_budget is not None and "five_hour" not in windows:
        windows.append("five_hour")
    if secondary_token_budget is not None and "weekly" not in windows:
        windows.append("weekly")
    return tuple(windows)


def infer_model_provider(model: str | None, owned_by: str | None = None) -> str:
    normalized = model.strip().lower() if isinstance(model, str) else ""
    if "claude" in normalized or "anthropic" in normalized:
        return "claude"
    if "grok" in normalized or normalized.startswith(("xai/", "xai-", "xai_")):
        return "xai"
    return normalize_provider(owned_by)


def catalog_label(model: str, owned_by: str | None = None) -> str:
    provider = infer_model_provider(model, owned_by)
    if provider == "claude":
        return f"Claude: {model}"
    if provider == "xai":
        return f"Grok: {model}"
    return f"CLIProxyAPI: {model}"


def catalog_owner(model: str, owned_by: str | None = None) -> str:
    provider = infer_model_provider(model, owned_by)
    if provider == "claude":
        return "anthropic"
    if provider == "xai":
        return "xai"
    return "cliproxyapi"
