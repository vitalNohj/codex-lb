from __future__ import annotations

import pytest

from app.core.clients.claude_sidecar import SidecarPrefix
from app.modules.proxy.sidecar_routing import (
    SIDECAR_PROVIDER_ORDER,
    SidecarRoutingEntry,
    apply_full_model_stars,
    parse_explicit_pool_target,
    resolve_sidecar_route,
)

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
            _entry("orcarouter", prefixes=(SidecarPrefix(prefix="minimax/minimax-", strip=False),)),
        ),
    )

    assert decision is not None
    assert decision.provider == "orcarouter"
    assert decision.wire_model == "minimax/minimax-m3"


def test_omniroute_entries_never_win_a_route_while_the_capability_is_disabled() -> None:
    """An OmniRoute entry cannot route, even as the only or longest match."""

    assert (
        resolve_sidecar_route(
            "omniroute/test-chat",
            (_entry("omniroute", full_models=("omniroute/test-chat",)),),
        )
        is None
    )
    # A longer OmniRoute prefix loses to a shorter enabled-provider prefix.
    decision = resolve_sidecar_route(
        "minimax/minimax-m3",
        (
            _entry("openrouter", prefixes=(SidecarPrefix(prefix="minimax/", strip=False),)),
            _entry("omniroute", prefixes=(SidecarPrefix(prefix="minimax/minimax-", strip=False),)),
        ),
    )
    assert decision is not None
    assert decision.provider == "openrouter"


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


def test_openai_compat_full_model_beats_openrouter_prefix() -> None:
    decision = resolve_sidecar_route(
        "z-ai/glm-5.3",
        (
            _entry("openrouter", prefixes=(SidecarPrefix(prefix="z-ai/", strip=False),)),
            _entry("openai_compat:nim", full_models=("z-ai/glm-5.3",)),
        ),
    )

    assert decision is not None
    assert decision.provider == "openai_compat:nim"
    assert decision.wire_model == "z-ai/glm-5.3"


def test_openai_compat_strip_prefix_forwards_wire_model() -> None:
    decision = resolve_sidecar_route(
        "nim/z-ai/glm-5.3",
        (_entry("openai_compat:nim", prefixes=(SidecarPrefix(prefix="nim/", strip=True),)),),
    )

    assert decision is not None
    assert decision.provider == "openai_compat:nim"
    assert decision.wire_model == "z-ai/glm-5.3"


def test_orcarouter_sits_between_openrouter_and_omniroute() -> None:
    # Deliberately the full tuple, not a relative-order subset: this is a
    # complete contract over the tiebreak order, and asserting only that
    # orcarouter sits between its two neighbours would stop noticing a provider
    # inserted anywhere else. A new integration is expected to update this line
    # as part of adding itself. ``opencode_go`` is last because it was added
    # last, and appending leaves every existing provider's relative rank
    # unchanged - an inserted entry would silently re-rank the providers after
    # it.
    assert SIDECAR_PROVIDER_ORDER == (
        "claude",
        "openrouter",
        "orcarouter",
        "omniroute",
        "ollama",
        "opencode_go",
    )


def test_unknown_provider_ranks_after_named_sidecars() -> None:
    decision = resolve_sidecar_route(
        "vast/qwen",
        (
            _entry(
                "openai_compat:2c9b8f3a-1e4d-4b7a-9c11-7a0e4d2b1c0a",
                prefixes=(SidecarPrefix(prefix="vast/", strip=True),),
            ),
            _entry("openrouter", prefixes=(SidecarPrefix(prefix="vast/", strip=True),)),
        ),
    )

    assert decision is not None
    assert decision.provider == "openrouter"


def test_openai_compat_prefix_still_routes() -> None:
    decision = resolve_sidecar_route(
        "vast/Qwen/Qwen2.5-7B",
        (
            _entry(
                "openai_compat:2c9b8f3a-1e4d-4b7a-9c11-7a0e4d2b1c0a",
                prefixes=(SidecarPrefix(prefix="vast/", strip=True),),
            ),
        ),
    )

    assert decision is not None
    assert decision.provider == "openai_compat:2c9b8f3a-1e4d-4b7a-9c11-7a0e4d2b1c0a"
    assert decision.wire_model == "Qwen/Qwen2.5-7B"


def test_openrouter_full_model_beats_openai_compat_prefix() -> None:
    decision = resolve_sidecar_route(
        "Qwen/Qwen2.5-7B",
        (
            _entry(
                "openai_compat:2c9b8f3a-1e4d-4b7a-9c11-7a0e4d2b1c0a",
                prefixes=(SidecarPrefix(prefix="Qwen/", strip=True),),
            ),
            _entry("openrouter", full_models=("Qwen/Qwen2.5-7B",)),
        ),
    )

    assert decision is not None
    assert decision.provider == "openrouter"
    assert decision.wire_model == "Qwen/Qwen2.5-7B"


def test_orcarouter_auto_is_forwarded_unstripped() -> None:
    decision = resolve_sidecar_route(
        "orcarouter/auto",
        (_entry("orcarouter", prefixes=(SidecarPrefix(prefix="orcarouter/", strip=False),)),),
    )

    assert decision is not None
    assert decision.provider == "orcarouter"
    assert decision.wire_model == "orcarouter/auto"


def test_starred_integration_wins_when_two_cards_list_the_same_full_model() -> None:
    entries = (
        _entry("openrouter", full_models=("z-ai/glm-5.3",)),
        _entry("orcarouter", full_models=("z-ai/glm-5.3",)),
    )
    starred = apply_full_model_stars(entries, {"z-ai/glm-5.3": "orcarouter"})

    decision = resolve_sidecar_route("Z-AI/GLM-5.3", starred)

    assert decision is not None
    assert decision.provider == "orcarouter"
    # Full models are forwarded as-is, preserving the requested case.
    assert decision.wire_model == "Z-AI/GLM-5.3"


def test_unstarred_duplicate_is_unroutable_for_bare_requests() -> None:
    """The same full model on several cards with no star is ambiguous.

    The star names the integration a bare request goes to; without it the bare
    id has no default route, so it stays unroutable instead of silently
    redirecting to the provider-rank winner. Alias pools must target it
    explicitly via ``<provider>::<model>``.
    """

    entries = (
        _entry("orcarouter", full_models=("z-ai/glm-5.3",)),
        _entry("openrouter", full_models=("z-ai/glm-5.3",)),
    )

    decision = resolve_sidecar_route("z-ai/glm-5.3", entries)

    assert decision is None


def test_star_that_names_a_card_not_listing_the_model_keeps_sole_card_routing() -> None:
    """The star map is advisory: a star only applies to the card it names.

    Here the star names orcarouter, which does not list the model, so the
    openrouter copy stays unstarred - and because it is the only enabled card
    listing the model, it keeps routing (the starless-sole-card compatibility
    rule) instead of becoming unroutable.
    """

    entries = (
        _entry("openrouter", full_models=("z-ai/glm-5.3",)),
        _entry("orcarouter", full_models=("other/model",)),
    )
    starred = apply_full_model_stars(entries, {"z-ai/glm-5.3": "orcarouter"})

    decision = resolve_sidecar_route("z-ai/glm-5.3", starred)

    assert decision is not None
    assert decision.provider == "openrouter"


def test_starless_duplicate_with_one_card_disabled_keeps_the_remaining_card() -> None:
    """A sole remaining card routes even starless (compatibility rule)."""

    entries = (
        _entry("orcarouter", full_models=("z-ai/glm-5.3",)),
        _entry("openrouter", full_models=("z-ai/glm-5.3",)),
    )
    # Simulate orcarouter being disabled: only openrouter remains enabled.
    remaining = (_entry("openrouter", full_models=("z-ai/glm-5.3",)),)

    assert resolve_sidecar_route("z-ai/glm-5.3", entries) is None
    decision = resolve_sidecar_route("z-ai/glm-5.3", remaining)

    assert decision is not None
    assert decision.provider == "openrouter"


def test_apply_full_model_stars_leaves_unnamed_entries_untouched() -> None:
    entries = (
        _entry("openrouter", full_models=("a",)),
        _entry("orcarouter", full_models=("b",)),
    )

    starred = apply_full_model_stars(entries, {"a": "openrouter"})

    assert starred[0].starred_full_models == frozenset({"a"})
    assert starred[1].starred_full_models == frozenset()


def test_explicit_pool_target_resolves_within_the_named_provider() -> None:
    entries = (
        _entry("openrouter", full_models=("z-ai/glm-5.3",)),
        _entry("orcarouter", full_models=("z-ai/glm-5.3",)),
    )

    decision = resolve_sidecar_route("orcarouter::z-ai/glm-5.3", entries)

    assert decision is not None
    assert decision.provider == "orcarouter"
    assert decision.wire_model == "z-ai/glm-5.3"


def test_explicit_pool_target_with_prefix_routes_and_strips_within_the_provider() -> None:
    entries = (
        _entry("openrouter", prefixes=(SidecarPrefix(prefix="or/", strip=True),)),
        _entry("ollama", prefixes=(SidecarPrefix(prefix="or/", strip=True),)),
    )

    decision = resolve_sidecar_route("ollama::or/llama3", entries)

    assert decision is not None
    assert decision.provider == "ollama"
    assert decision.wire_model == "llama3"


def test_explicit_pool_target_for_unknown_provider_is_unroutable() -> None:
    entries = (_entry("openrouter", full_models=("z-ai/glm-5.3",)),)

    decision = resolve_sidecar_route("orcarouter::z-ai/glm-5.3", entries)

    assert decision is None


def test_explicit_target_for_known_but_absent_provider_never_falls_through() -> None:
    """A target naming a known integration without an enabled entry is unroutable.

    Falling through to bare-model matching would let another integration claim
    the literal target - here the openrouter prefix ``orcarouter::`` would
    otherwise strip the target and serve it, defeating the explicit route.
    """

    entries = (_entry("openrouter", prefixes=(SidecarPrefix(prefix="orcarouter::", strip=True),)),)

    decision = resolve_sidecar_route("orcarouter::z-ai/glm-5.3", entries)

    assert decision is None


def test_full_model_id_containing_the_separator_resolves_as_a_bare_model() -> None:
    """A configured full-model id that itself contains ``::`` wins exactly.

    The full-model pass runs before explicit-target parsing, so a bare request
    for ``openrouter::weird/id`` resolves against the configured id instead of
    being parsed as the pool target ``openrouter::weird/id`` (whose model part
    matches nothing on the openrouter card).
    """

    entries = (
        _entry("openrouter", full_models=("openrouter::weird/id",)),
        _entry("orcarouter", prefixes=(SidecarPrefix(prefix="openrouter/", strip=True),)),
    )

    decision = resolve_sidecar_route("openrouter::weird/id", entries)

    assert decision is not None
    assert decision.provider == "openrouter"
    assert decision.wire_model == "openrouter::weird/id"


def test_double_colon_id_with_unknown_provider_prefix_falls_through_to_prefix_pass() -> None:
    """``::`` ids whose leading segment names no known provider stay bare ids."""

    entries = (_entry("openrouter", prefixes=(SidecarPrefix(prefix="a", strip=False),)),)

    decision = resolve_sidecar_route("a::b/c", entries)

    assert decision is not None
    assert decision.provider == "openrouter"
    assert decision.wire_model == "a::b/c"


def test_parse_explicit_pool_target_splits_and_normalizes() -> None:
    assert parse_explicit_pool_target("OrcaRouter::Z-AI/GLM-5.3") == ("orcarouter", "Z-AI/GLM-5.3")
    assert parse_explicit_pool_target(" openrouter :: model ") == ("openrouter", "model")
    assert parse_explicit_pool_target("z-ai/glm-5.3") is None
    assert parse_explicit_pool_target("::model") is None
    assert parse_explicit_pool_target("provider::") is None
    assert parse_explicit_pool_target("a::b::c") == ("a", "b::c")
