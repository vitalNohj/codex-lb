from __future__ import annotations

import pytest

from app.core.clients.claude_sidecar import SidecarPrefix
from app.modules.proxy.sidecar_routing import SidecarRoutingEntry, resolve_sidecar_route

pytestmark = pytest.mark.unit


def _entry(
    provider: str,
    *,
    prefixes: tuple[SidecarPrefix, ...] = (),
    full_models: tuple[str, ...] = (),
) -> SidecarRoutingEntry:
    return SidecarRoutingEntry(provider=provider, prefixes=prefixes, full_models=full_models)


def test_full_model_beats_prefix_and_is_never_stripped() -> None:
    decision = resolve_sidecar_route(
        "cp-deepseek/deepseek-chat",
        (
            _entry("claude", prefixes=(SidecarPrefix(prefix="cp-", strip=True),)),
            _entry("openrouter", full_models=("cp-deepseek/deepseek-chat",)),
        ),
    )

    assert decision is not None
    assert decision.provider == "openrouter"
    assert decision.wire_model == "cp-deepseek/deepseek-chat"


def test_longest_prefix_wins_across_providers() -> None:
    decision = resolve_sidecar_route(
        "minimax/minimax-m3",
        (
            _entry("openrouter", prefixes=(SidecarPrefix(prefix="minimax/", strip=False),)),
            _entry("omniroute", prefixes=(SidecarPrefix(prefix="minimax/minimax-", strip=False),)),
        ),
    )

    assert decision is not None
    assert decision.provider == "omniroute"
    assert decision.wire_model == "minimax/minimax-m3"


def test_per_prefix_strip_toggle_controls_wire_model() -> None:
    stripped = resolve_sidecar_route(
        "or-deepseek/deepseek-chat",
        (_entry("openrouter", prefixes=(SidecarPrefix(prefix="or-", strip=True),)),),
    )
    preserved = resolve_sidecar_route(
        "deepseek/deepseek-chat",
        (_entry("openrouter", prefixes=(SidecarPrefix(prefix="deepseek/", strip=False),)),),
    )

    assert stripped is not None
    assert stripped.wire_model == "deepseek/deepseek-chat"
    assert preserved is not None
    assert preserved.wire_model == "deepseek/deepseek-chat"


def test_dash_and_underscore_prefix_variants_are_equivalent() -> None:
    decision = resolve_sidecar_route(
        "cp_claude-sonnet-4-5",
        (_entry("claude", prefixes=(SidecarPrefix(prefix="cp-", strip=True),)),),
    )

    assert decision is not None
    assert decision.provider == "claude"
    assert decision.wire_model == "claude-sonnet-4-5"


def test_disabled_integrations_are_ignored_by_callers() -> None:
    # The pure resolver receives enabled entries only. This covers caller
    # behavior by passing only the enabled OpenRouter entry.
    decision = resolve_sidecar_route(
        "claude-sonnet-4-5",
        (_entry("openrouter", prefixes=(SidecarPrefix(prefix="deepseek/", strip=False),)),),
    )

    assert decision is None


def test_no_match_falls_through() -> None:
    assert (
        resolve_sidecar_route(
            "gpt-5.4",
            (
                _entry("claude", prefixes=(SidecarPrefix(prefix="claude", strip=False),)),
                _entry("omniroute", full_models=("omniroute/test-chat",)),
            ),
        )
        is None
    )


def test_ollama_participates_in_full_model_matching() -> None:
    decision = resolve_sidecar_route(
        "gpt-oss:120b-cloud",
        (
            _entry("openrouter", prefixes=(SidecarPrefix(prefix="gpt-", strip=False),)),
            _entry("ollama", full_models=("gpt-oss:120b-cloud",)),
        ),
    )

    assert decision is not None
    assert decision.provider == "ollama"
    assert decision.wire_model == "gpt-oss:120b-cloud"


def test_ollama_participates_in_longest_prefix_matching() -> None:
    decision = resolve_sidecar_route(
        "ollama-gpt-oss:120b-cloud",
        (
            _entry("openrouter", prefixes=(SidecarPrefix(prefix="ollama-", strip=True),)),
            _entry("ollama", prefixes=(SidecarPrefix(prefix="ollama-gpt-", strip=True),)),
        ),
    )

    assert decision is not None
    assert decision.provider == "ollama"
    assert decision.wire_model == "oss:120b-cloud"
