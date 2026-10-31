"""Client-facing CLIProxyAPI ids for the dashboard model pickers.

CLIProxyAPI's ``/v1/models`` list includes one ``lb<hash>/<model>`` alias per
credential. Those aliases are not what clients send. Request logs and limit
matching record the client model (``cc/claude-opus-5-5``, or a configured full
model), and a filter stores that string exactly.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Mapping, Sequence

from app.core.clients.claude_sidecar import (
    ClaudeSidecarClient,
    ClaudeSidecarConfig,
    ClaudeSidecarError,
    SidecarPrefix,
)
from app.core.types import JsonValue
from app.modules.proxy.sidecar_model_profiles import apply_sidecar_model_profile_with_suffix_effort
from app.modules.proxy.sidecar_routing import (
    SidecarRoutingEntry,
    prefix_variants,
    resolve_sidecar_route,
)

logger = logging.getLogger(__name__)

# CLIProxyAPI subscription logins the limit-rules picker may offer. Codex
# models are served by the Codex routes, so a ChatGPT/Codex auth file is not
# a subscription source here even when CLIProxyAPI lists it.
SUBSCRIPTION_AUTH_PROVIDERS = frozenset({"claude", "xai"})

# ``generated_prefix`` is ``lb`` plus 10 hex digits, or that plus ``-<n>`` when
# the first spelling is already taken. The following path segment is the model.
_ACCOUNT_PREFIX = re.compile(r"lb[0-9a-f]{10}(?:-\d+)?\Z", re.IGNORECASE)


def cliproxy_picker_model_ids(
    discovered_ids: Sequence[str],
    *,
    prefixes: Sequence[SidecarPrefix],
    full_models: Sequence[str],
) -> list[str]:
    """Ids a picker may store so a later request on that id hits the rule.

    Strip-prefix aliases of each upstream model (``cc/claude-opus-5-5``), the
    upstream id itself when a client can send it unchanged, and every
    configured full model. Per-account ``lb<hash>/`` aliases are omitted; the
    model after the alias is kept, so ``lb…/claude-sonnet-5`` still offers
    ``cc/claude-sonnet-5``.
    """

    entries = (
        SidecarRoutingEntry(
            provider="claude",
            prefixes=tuple(prefixes),
            full_models=tuple(full_models),
        ),
    )
    strip_variants = tuple(
        variant for prefix in prefixes if prefix.strip for variant in prefix_variants(prefix.prefix) if variant
    )
    ids: list[str] = []
    seen: set[str] = set()

    def add(model_id: str) -> None:
        text = model_id.strip()
        if not text or _is_account_alias(text):
            return
        key = text.casefold()
        if key in seen:
            return
        seen.add(key)
        ids.append(text)

    for full in full_models:
        add(full)

    upstream: list[str] = []
    seen_upstream: set[str] = set()
    for discovered in discovered_ids:
        body = _model_after_account_alias(discovered)
        if body is None:
            continue
        key = body.casefold()
        if key in seen_upstream:
            continue
        seen_upstream.add(key)
        upstream.append(body)

    for base in upstream:
        lowered = base.casefold()
        # A discovered id may begin with a stripping prefix (``claude-`` and
        # ``claude-sonnet-4-6``). That does not make it the client id: routing
        # would remove the prefix and forward a different model. Offer
        # ``<prefix><id>`` when that alias forwards this id, and keep the
        # discovered id only when dispatch leaves it unchanged.
        for variant in strip_variants:
            alias = f"{variant}{base}"
            decision = resolve_sidecar_route(alias, entries)
            if decision is None or decision.provider != "claude":
                continue
            if _dispatch_model(decision.wire_model).casefold() != lowered:
                continue
            add(alias)
        decision = resolve_sidecar_route(base, entries)
        if decision is None or decision.provider != "claude":
            continue
        if _dispatch_model(decision.wire_model) != base:
            continue
        add(base)
    return ids


def _dispatch_model(wire_model: str) -> str:
    dispatched, _effort_from_name = apply_sidecar_model_profile_with_suffix_effort({}, stripped_model=wire_model)
    return dispatched


def _is_account_alias(model_id: str) -> bool:
    return any(_ACCOUNT_PREFIX.fullmatch(segment) for segment in model_id.split("/") if segment)


def _model_after_account_alias(model_id: str) -> str | None:
    text = model_id.strip()
    while text and _ACCOUNT_PREFIX.fullmatch(text.split("/", 1)[0]):
        _prefix, separator, rest = text.partition("/")
        if not separator:
            return None
        text = rest.strip()
    if not text or _is_account_alias(text):
        return None
    return text


async def subscription_picker_model_ids(
    client: ClaudeSidecarClient,
    config: ClaudeSidecarConfig,
) -> list[str]:
    """Client ids served by Claude and xAI CLIProxyAPI subscription logins.

    The provider comes from each auth-file listing, and the models from that
    file's catalog. A Codex/ChatGPT login and any other provider are skipped.
    An unreachable catalog contributes nothing rather than failing the picker.
    """

    try:
        auth_files = await client.list_auth_files()
    except ClaudeSidecarError:
        logger.warning("failed to list CLIProxyAPI auth files for the subscription model picker", exc_info=True)
        return []
    selected = [
        entry
        for entry in auth_files
        if _auth_provider(entry) in SUBSCRIPTION_AUTH_PROVIDERS and _auth_file_name(entry) is not None
    ]
    catalogs = await asyncio.gather(
        *(_auth_file_catalog(client, name) for name in (_auth_file_name(entry) for entry in selected)),
        return_exceptions=True,
    )
    discovered: list[str] = []
    for catalog in catalogs:
        if isinstance(catalog, BaseException):
            if isinstance(catalog, asyncio.CancelledError):
                raise catalog
            logger.warning(
                "failed to read a CLIProxyAPI subscription auth-file catalog",
                exc_info=catalog,
            )
            continue
        discovered.extend(catalog)
    return cliproxy_picker_model_ids(
        discovered,
        prefixes=config.prefixes,
        full_models=config.full_models,
    )


async def _auth_file_catalog(client: ClaudeSidecarClient, name: str | None) -> list[str]:
    if name is None:
        return []
    return await client.list_auth_file_models(name)


def _auth_provider(entry: Mapping[str, JsonValue]) -> str | None:
    provider = entry.get("provider")
    if not isinstance(provider, str):
        return None
    return provider.strip().casefold() or None


def _auth_file_name(entry: Mapping[str, JsonValue]) -> str | None:
    name = entry.get("name")
    if not isinstance(name, str):
        return None
    return name.strip() or None
