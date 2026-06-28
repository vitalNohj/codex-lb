"""User-configurable model aliasing.

A request may use an alias model name (e.g. ``custom_r1``) that resolves to a
real upstream model id (e.g. ``cc/claude``). Resolving the alias to the real
model *before* sidecar routing means the prefix/full-model matchers and the
forwarded upstream model both operate on the real id, exactly as if the client
had sent it directly.

The alias map is stored on ``DashboardSettings.model_aliases_json`` as
``{alias: real_model}`` and is edited from the dashboard Routing settings.
"""

from __future__ import annotations

import logging

from app.core.config.settings_cache import get_settings_cache
from app.core.utils.request_id import get_request_id
from app.modules.settings.service import parse_model_aliases

logger = logging.getLogger(__name__)


def resolve_model_alias(model: str | None, aliases: dict[str, str]) -> str | None:
    """Return the real model for ``model`` or ``model`` itself when unaliased.

    Matching is case-insensitive on the alias key. ``None`` in -> ``None`` out.
    """

    if model is None:
        return None
    if not aliases:
        return model
    normalized = model.strip()
    if not normalized:
        return model
    lowered = normalized.lower()
    for alias, target in aliases.items():
        if alias.strip().lower() == lowered:
            return target
    return model


async def load_model_aliases() -> dict[str, str]:
    try:
        dashboard_settings = await get_settings_cache().get()
    except Exception:
        logger.warning("failed to load dashboard settings for model aliasing", exc_info=True)
        return {}
    return parse_model_aliases(dashboard_settings.model_aliases_json)


async def resolve_request_model_alias(model: str | None) -> str | None:
    """Resolve ``model`` against the configured alias map, logging rewrites."""

    aliases = await load_model_aliases()
    resolved = resolve_model_alias(model, aliases)
    if resolved is not None and model is not None and resolved != model:
        logger.info(
            "model_alias_resolved request_id=%s requested_model=%s resolved_model=%s",
            get_request_id(),
            model,
            resolved,
        )
    return resolved
