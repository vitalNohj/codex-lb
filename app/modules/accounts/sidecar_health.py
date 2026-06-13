from __future__ import annotations

_RECORDED_HEALTH_STATUSES: frozenset[str] = frozenset({"unreachable", "unauthorized", "healthy", "error"})


def resolve_sidecar_health_status(
    *,
    enabled: bool,
    api_key_configured: bool,
    recorded_status: str | None,
) -> str:
    if not enabled:
        return "disabled"
    if not api_key_configured:
        return "missing_api_key"
    if recorded_status in _RECORDED_HEALTH_STATUSES:
        return recorded_status
    return "healthy"
