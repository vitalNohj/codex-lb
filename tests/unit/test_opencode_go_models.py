from __future__ import annotations

import pytest

from app.modules.proxy.opencode_go_models import (
    OPENCODE_GO_MODEL_PROTOCOLS,
    OpenCodeGoProtocol,
    is_opencode_go_model_supported,
    opencode_go_model_profile,
    opencode_go_model_protocol,
    supported_opencode_go_model_ids,
    unsupported_model_message,
)

pytestmark = pytest.mark.unit


# Transcribed from the official https://opencode.ai/docs/go endpoint table. This
# is the pinned, reviewed source; models.dev disagrees on the Qwen ids because
# it records no provider override there, and an absent override is not a
# protocol declaration.
@pytest.mark.parametrize(
    ("model", "protocol"),
    [
        ("glm-5.3", OpenCodeGoProtocol.CHAT_COMPLETIONS),
        ("kimi-k2.7-code", OpenCodeGoProtocol.CHAT_COMPLETIONS),
        ("deepseek-v4-flash-vision-exp", OpenCodeGoProtocol.CHAT_COMPLETIONS),
        ("hy3", OpenCodeGoProtocol.CHAT_COMPLETIONS),
        ("minimax-m3", OpenCodeGoProtocol.MESSAGES),
        ("qwen3.7-plus", OpenCodeGoProtocol.MESSAGES),
        ("qwen3.8-max", OpenCodeGoProtocol.MESSAGES),
        ("grok-4.6", OpenCodeGoProtocol.RESPONSES),
        ("gpt-5.6-luna", OpenCodeGoProtocol.RESPONSES),
        ("muse-spark-1.3-contributor", OpenCodeGoProtocol.RESPONSES),
    ],
)
def test_documented_protocol_map(model: str, protocol: OpenCodeGoProtocol) -> None:
    assert opencode_go_model_protocol(model) is protocol


def test_qwen_models_are_messages_not_chat_completions() -> None:
    # Regression guard for the specific drift the research found: routing these
    # to /chat/completions produces an upstream format rejection that reads to a
    # client like a bad prompt rather than a routing bug.
    for model in ("qwen3.6-plus", "qwen3.7-plus", "qwen3.7-max", "qwen3.8-max", "qwen3.8-flash"):
        assert opencode_go_model_protocol(model) is OpenCodeGoProtocol.MESSAGES
        assert not is_opencode_go_model_supported(model)


def test_unknown_model_is_unknown_not_guessed_onto_a_default() -> None:
    assert opencode_go_model_protocol("some-model-we-never-reviewed") is OpenCodeGoProtocol.UNKNOWN
    assert not is_opencode_go_model_supported("some-model-we-never-reviewed")


def test_model_ids_are_matched_case_insensitively_and_trimmed() -> None:
    assert opencode_go_model_protocol("  GLM-5.3  ") is OpenCodeGoProtocol.CHAT_COMPLETIONS
    assert is_opencode_go_model_supported("GLM-5.3")


def test_only_chat_completions_models_are_supported() -> None:
    for model_id, profile in OPENCODE_GO_MODEL_PROTOCOLS.items():
        expected = profile.protocol is OpenCodeGoProtocol.CHAT_COMPLETIONS and not profile.privacy_sensitive
        assert is_opencode_go_model_supported(model_id) is expected


def test_privacy_sensitive_models_are_never_supported() -> None:
    for model in ("muse-spark-1.3-contributor", "muse-spark-1.2-contributor"):
        # Go's own Privacy table records training on prompts/completions and
        # non-ZDR retention. The flag is independent of protocol so a later
        # protocol expansion cannot enable them as a side effect.
        assert opencode_go_model_profile(model).privacy_sensitive
        assert not is_opencode_go_model_supported(model)


def test_supported_launch_set_is_the_documented_chat_completions_catalogue() -> None:
    assert set(supported_opencode_go_model_ids()) == {
        "glm-5.3-flash",
        "glm-5.3",
        "glm-5.2",
        "glm-5.1",
        "kimi-k3",
        "kimi-k2.7-code",
        "kimi-k2.6",
        "longcat-2.0",
        "deepseek-v4.1-flash",
        "deepseek-v4-pro",
        "deepseek-v4-flash",
        "deepseek-v4-flash-vision-exp",
        "mimo-v2.5",
        "mimo-v2.5-pro",
        "hy4-preview",
        "hy3",
    }


def test_unsupported_message_names_the_real_endpoint() -> None:
    # The model may well exist and work in the OpenCode CLI; it is this
    # integration that does not speak its endpoint. Saying "unknown model" would
    # send an operator debugging in the wrong direction.
    assert "/messages" in unsupported_model_message("qwen3.7-plus")
    assert "/responses" in unsupported_model_message("grok-4.6")
    assert "not a reviewed OpenCode Go model" in unsupported_model_message("nope-1")
    assert "training" in unsupported_model_message("muse-spark-1.3-contributor")
