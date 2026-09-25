"""Save-time validation for alias pools (``_validate_model_alias_pools``)."""

from __future__ import annotations

from dataclasses import replace

import pytest

from app.core.clients.claude_sidecar import SidecarPrefix
from app.modules.settings.model_alias_pools import ModelAliasPool
from app.modules.settings.schemas import DashboardSettingsUpdateRequest, ModelAliasPoolSchema
from app.modules.settings.service import (
    DashboardSettingsUpdateData,
    ModelAliasPoolError,
)
from app.modules.settings.service import (
    _validate_model_alias_pools as _validate_against_stored,
)
from tests.unit.test_settings_service import _openai_compat_endpoints, _settings_update

pytestmark = pytest.mark.unit


def _pool(*targets: str) -> ModelAliasPool:
    return ModelAliasPool(targets=targets)


def _validate_model_alias_pools(
    payload: DashboardSettingsUpdateData,
    *,
    stored: dict[str, ModelAliasPool] | None = None,
) -> None:
    """Validate ``payload`` as a save over ``stored`` (nothing stored by default)."""

    _validate_against_stored(payload, stored_aliases=stored or {})


def _payload(aliases: dict[str, ModelAliasPool | str | dict[str, list[str]]]) -> DashboardSettingsUpdateData:
    """Routing: OpenRouter ``or/`` and OrcaRouter ``orca/`` enabled and pool-capable,
    CLIProxyAPI ``cc/`` enabled but not pool-capable, one OpenAI-compat endpoint
    with full model ``z-ai/glm-5.3``. Anything else routes to native Codex."""

    payload = _settings_update(
        claude_prefixes=[SidecarPrefix(prefix="cc/", strip=True)],
        openrouter_prefixes=[SidecarPrefix(prefix="or/", strip=True)],
        orcarouter_prefixes=[SidecarPrefix(prefix="orca/", strip=True)],
        openai_compat_endpoints=_openai_compat_endpoints(models=["z-ai/glm-5.3"]),
    )
    return replace(
        payload,
        claude_sidecar_enabled=True,
        openrouter_sidecar_enabled=True,
        orcarouter_sidecar_enabled=True,
        model_aliases=aliases,  # type: ignore[arg-type]
    )


def test_accepts_single_target_alias_to_native_codex() -> None:
    _validate_model_alias_pools(_payload({"fast": _pool("gpt-5.4")}))


def test_accepts_single_target_alias_to_non_pool_capable_sidecar() -> None:
    _validate_model_alias_pools(_payload({"claude": _pool("cc/claude-opus")}))


def test_accepts_pool_across_pool_capable_providers() -> None:
    _validate_model_alias_pools(_payload({"pooled/glm": _pool("or/z-ai/glm-5.3", "orca/glm-5.3", "z-ai/glm-5.3")}))


def test_rejects_pool_with_native_codex_target() -> None:
    with pytest.raises(ModelAliasPoolError) as exc_info:
        _validate_model_alias_pools(_payload({"pooled/glm": _pool("or/z-ai/glm-5.3", "gpt-5.4")}))

    assert exc_info.value.alias == "pooled/glm"
    assert exc_info.value.target == "gpt-5.4"
    assert "native Codex" in str(exc_info.value)


def test_rejects_pool_with_non_pool_capable_sidecar_target() -> None:
    with pytest.raises(ModelAliasPoolError) as exc_info:
        _validate_model_alias_pools(_payload({"pooled/glm": _pool("or/z-ai/glm-5.3", "cc/glm")}))

    assert exc_info.value.target == "cc/glm"
    assert "CLIProxyAPI" in str(exc_info.value)
    assert "does not support pooling" in str(exc_info.value)


def test_accepts_turning_off_an_integration_a_stored_pool_uses() -> None:
    stored = {"pooled/glm": _pool("or/a", "orca/b")}
    payload = replace(_payload(dict(stored)), orcarouter_sidecar_enabled=False)

    _validate_model_alias_pools(payload, stored=stored)


def test_accepts_new_pool_target_on_a_turned_off_pool_capable_integration() -> None:
    # Off is an operational switch: the proxy skips the target until it is
    # back on, so the pool may be edited around it meanwhile.
    payload = replace(_payload({"pooled/glm": _pool("orca/b", "or/a")}), orcarouter_sidecar_enabled=False)

    _validate_model_alias_pools(payload, stored={"pooled/glm": _pool("or/a", "orca/b")})


def test_rejects_new_pool_target_on_a_turned_off_non_pool_capable_integration() -> None:
    payload = replace(_payload({"pooled/glm": _pool("or/a", "cc/glm")}), claude_sidecar_enabled=False)

    with pytest.raises(ModelAliasPoolError) as exc_info:
        _validate_model_alias_pools(payload)

    assert exc_info.value.target == "cc/glm"
    assert "does not support pooling" in str(exc_info.value)


def test_turned_off_integration_does_not_shadow_the_route_a_target_takes_now() -> None:
    # CLIProxyAPI is off but claims the longer prefix ``or/cc``; the target
    # routes to OpenRouter today, so it is judged by that route.
    payload = replace(
        _payload({"pooled/glm": _pool("or/cc-glm", "orca/b")}),
        claude_sidecar_enabled=False,
        claude_sidecar_model_prefixes=[SidecarPrefix(prefix="or/cc", strip=True)],
    )

    _validate_model_alias_pools(payload)


def test_unchanged_stored_pool_is_not_re_judged_when_routing_changes() -> None:
    # The pool was valid when saved; a later routing edit that leaves a target
    # unroutable must not block unrelated saves. The proxy skips that target.
    stored = {"pooled/glm": _pool("or/a", "gpt-5.4")}

    _validate_model_alias_pools(_payload(dict(stored)), stored=stored)


def test_changed_pool_is_judged_in_full() -> None:
    stored = {"pooled/glm": _pool("or/a", "gpt-5.4")}

    with pytest.raises(ModelAliasPoolError) as exc_info:
        _validate_model_alias_pools(_payload({"pooled/glm": _pool("gpt-5.4", "or/a")}), stored=stored)

    assert exc_info.value.target == "gpt-5.4"
    assert "native Codex" in str(exc_info.value)


def test_rejects_alias_as_target() -> None:
    with pytest.raises(ModelAliasPoolError) as exc_info:
        _validate_model_alias_pools(_payload({"a": _pool("or/x"), "b": _pool("A")}))

    assert exc_info.value.alias == "b"
    assert exc_info.value.target == "A"
    assert "cannot chain" in str(exc_info.value)


def test_keeps_stored_legacy_chains_on_an_unrelated_save() -> None:
    # Legacy single-step aliases could name another alias, or themselves; the
    # migration carries them over and every save sends them back unchanged.
    stored = {"fast": _pool("gpt-5.4"), "gpt-5.4": _pool("cc/claude"), "x": _pool("x")}

    _validate_model_alias_pools(_payload(dict(stored)), stored=stored)


def test_rejects_chain_created_by_editing_a_stored_chaining_alias() -> None:
    stored = {"fast": _pool("gpt-5.4"), "gpt-5.4": _pool("cc/claude")}

    with pytest.raises(ModelAliasPoolError) as exc_info:
        _validate_model_alias_pools(
            _payload({"fast": _pool("gpt-5.4", "or/x"), "gpt-5.4": _pool("cc/claude")}), stored=stored
        )

    assert exc_info.value.alias == "fast"
    assert exc_info.value.target == "gpt-5.4"


def test_rejects_chain_created_by_adding_an_alias_another_alias_targets() -> None:
    stored = {"fast": _pool("or/x", "orca/y")}

    with pytest.raises(ModelAliasPoolError) as exc_info:
        _validate_model_alias_pools(_payload({"fast": _pool("or/x", "orca/y"), "or/x": _pool("orca/z")}), stored=stored)

    assert exc_info.value.alias == "fast"
    assert exc_info.value.target == "or/x"
    assert "cannot chain" in str(exc_info.value)


def test_rejects_duplicate_target() -> None:
    with pytest.raises(ModelAliasPoolError) as exc_info:
        _validate_model_alias_pools(_payload({"pooled": _pool("or/x", "OR/X")}))

    assert exc_info.value.target == "OR/X"
    assert "more than once" in str(exc_info.value)


def test_rejects_empty_pool() -> None:
    with pytest.raises(ModelAliasPoolError) as exc_info:
        _validate_model_alias_pools(_payload({"pooled": {"targets": []}}))

    assert exc_info.value.alias == "pooled"
    assert "no targets" in str(exc_info.value)


def test_rejects_too_many_targets() -> None:
    targets = tuple(f"or/model-{index}" for index in range(17))

    with pytest.raises(ModelAliasPoolError) as exc_info:
        _validate_model_alias_pools(_payload({"pooled": _pool(*targets)}))

    assert "more than 16" in str(exc_info.value)


def test_error_carries_no_target_for_alias_level_problems() -> None:
    with pytest.raises(ModelAliasPoolError) as exc_info:
        _validate_model_alias_pools(_payload({"pooled": {"targets": []}}))

    assert exc_info.value.target is None


def test_update_request_accepts_legacy_and_pool_shapes() -> None:
    payload = DashboardSettingsUpdateRequest.model_validate(
        {
            "modelAliases": {
                "legacy": " cc/claude ",
                "pooled/glm": {"targets": ["or/a", " orca/b ", "or/A"]},
            }
        }
    )

    assert payload.model_aliases == {
        "legacy": ModelAliasPoolSchema(targets=["cc/claude"]),
        "pooled/glm": ModelAliasPoolSchema(targets=["or/a", "orca/b"]),
    }


def test_update_request_rejects_pool_without_targets() -> None:
    with pytest.raises(ValueError, match="no targets"):
        DashboardSettingsUpdateRequest.model_validate({"modelAliases": {"pooled": {"targets": []}}})
    with pytest.raises(ValueError, match="no targets"):
        DashboardSettingsUpdateRequest.model_validate({"modelAliases": {"pooled": "  "}})


def test_update_request_rejects_malformed_pool_value() -> None:
    with pytest.raises(ValueError):
        DashboardSettingsUpdateRequest.model_validate({"modelAliases": {"pooled": {"targets": "or/a"}}})
    with pytest.raises(ValueError):
        DashboardSettingsUpdateRequest.model_validate({"modelAliases": {"pooled": 7}})
