"""Client-facing CLIProxyAPI ids for the dashboard model pickers.

CLIProxyAPI's ``/v1/models`` list includes one ``lb<hash>/<model>`` alias per
credential. Those aliases are not what clients send. Request logs and limit
matching record the client model (``cc/claude-opus-5-5``, or a configured full
model), and a filter stores that string exactly.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from app.core.clients.claude_sidecar import SidecarPrefix
from app.modules.proxy.sidecar_model_profiles import apply_sidecar_model_profile_with_suffix_effort
from app.modules.proxy.sidecar_routing import (
    SidecarRoutingEntry,
    prefix_variants,
    resolve_sidecar_route,
)

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
        if any(lowered.startswith(variant) for variant in strip_variants):
            if _owns(base, entries):
                add(base)
            continue
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


def _owns(model_id: str, entries: tuple[SidecarRoutingEntry, ...]) -> bool:
    decision = resolve_sidecar_route(model_id, entries)
    return decision is not None and decision.provider == "claude"


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
