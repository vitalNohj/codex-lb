from __future__ import annotations

from app.core.clients.claude_sidecar import SidecarPrefix
from app.modules.api_keys.model_filters import encode_model_filters, limit_matches_request_model
from app.modules.proxy.cliproxy_picker_models import cliproxy_picker_model_ids

_ACCOUNT_ALIAS = "lb2a7d4938e6/claude-sonnet-5"
_COLLISION_ALIAS = "lb2a7d4938e6-2/claude-haiku-4-5-20251001"


def test_picker_lists_prefix_forms_and_full_models_without_account_aliases() -> None:
    ids = cliproxy_picker_model_ids(
        (
            _ACCOUNT_ALIAS,
            "claude-opus-4-20250514",
            "grok-4.6",
            _COLLISION_ALIAS,
            "claude-sonnet-4-6",
            "claude-opus-5-5",
        ),
        prefixes=(SidecarPrefix(prefix="cc/", strip=True),),
        full_models=("claude-opus-5-5",),
    )

    assert "cc/claude-opus-5-5" in ids
    assert "cc/claude-sonnet-5" in ids
    assert "cc/grok-4.6" in ids
    assert "cc/claude-haiku-4-5-20251001" in ids
    assert "cc/claude-sonnet-4-6" in ids
    assert "cc/claude-opus-4-20250514" in ids
    assert "claude-opus-5-5" in ids
    assert _ACCOUNT_ALIAS not in ids
    assert _COLLISION_ALIAS not in ids
    assert all("lb2a7d4938e6" not in model_id for model_id in ids)
    assert ids.count("cc/claude-opus-5-5") == 1
    assert ids.count("claude-opus-5-5") == 1


def test_picked_prefix_matches_the_client_model_limit_rules_compare() -> None:
    """Limits and request logs store the client model, not the account alias."""

    ids = cliproxy_picker_model_ids(
        (_ACCOUNT_ALIAS, "claude-opus-5-5", "grok-4.6"),
        prefixes=(SidecarPrefix(prefix="cc/", strip=True),),
        full_models=("claude-opus-5-5",),
    )
    picked = next(model_id for model_id in ids if model_id == "cc/claude-opus-5-5")
    stored = encode_model_filters([picked])

    assert limit_matches_request_model(stored, "cc/claude-opus-5-5") is True
    assert limit_matches_request_model(stored, _ACCOUNT_ALIAS) is False
    legacy = encode_model_filters([_ACCOUNT_ALIAS])
    assert limit_matches_request_model(legacy, _ACCOUNT_ALIAS) is True
    assert limit_matches_request_model(legacy, "cc/claude-opus-5-5") is False


def test_non_stripping_prefix_lists_the_model_clients_send_unchanged() -> None:
    ids = cliproxy_picker_model_ids(
        ("claude-sonnet", "grok-4.6"),
        prefixes=(SidecarPrefix(prefix="claude", strip=False),),
        full_models=(),
    )

    assert ids == ["claude-sonnet"]


def test_stripping_and_plain_prefixes_both_stay_selectable() -> None:
    ids = cliproxy_picker_model_ids(
        (_ACCOUNT_ALIAS,),
        prefixes=(
            SidecarPrefix(prefix="claude", strip=False),
            SidecarPrefix(prefix="cc/", strip=True),
        ),
        full_models=(),
    )

    assert ids == ["cc/claude-sonnet-5", "claude-sonnet-5"]


def test_upstream_id_that_starts_with_a_stripping_prefix_is_prefixed_again() -> None:
    """``claude-`` + ``claude-sonnet-4-6`` must not be offered as the bare id.

    Routing would strip ``claude-`` and forward ``sonnet-4-6``. The client id
    that forwards the discovered model is ``claude-claude-sonnet-4-6``.
    """

    ids = cliproxy_picker_model_ids(
        ("claude-sonnet-4-6",),
        prefixes=(SidecarPrefix(prefix="claude-", strip=True),),
        full_models=(),
    )

    assert "claude-claude-sonnet-4-6" in ids
    assert "claude-sonnet-4-6" not in ids


def test_discovered_client_prefix_round_trips_to_that_discovered_id() -> None:
    ids = cliproxy_picker_model_ids(
        ("cc/claude-opus-5-5",),
        prefixes=(SidecarPrefix(prefix="cc/", strip=True),),
        full_models=(),
    )

    assert ids == ["cc/cc/claude-opus-5-5"]


def test_configured_full_model_is_listed_when_discovery_is_empty() -> None:
    ids = cliproxy_picker_model_ids(
        (),
        prefixes=(SidecarPrefix(prefix="cc/", strip=True),),
        full_models=("grok-4.6", "lb2a7d4938e6/grok-4.6"),
    )

    assert ids == ["grok-4.6"]
