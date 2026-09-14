"""Pinned OpenCode Go model/protocol map.

OpenCode Go serves different models on three different upstream endpoints, and
which model lives where is *per model, not per family*. Getting it wrong does
not fail loudly: the upstream answers a wrongly-shaped request with a 400 whose
text names a format, which reads to a client like a bad prompt rather than a
routing bug.

The map below is transcribed from the official endpoint table on
https://opencode.ai/docs/go. It is deliberately **pinned and reviewed** rather
than synced from any external catalogue:

* The live ``GET /zen/go/v1/models`` listing publishes only ``id``, ``object``,
  ``created`` and ``owned_by``. It carries no endpoint or protocol field at all,
  so it cannot answer this question.
* models.dev does carry a protocol hint, but it disagrees with the official docs
  on the Qwen ids, where it records no ``provider.npm`` override and therefore
  silently inherits an OpenAI-compatible default. An *absent* override is not a
  protocol declaration, and treating it as one would route Anthropic-shaped
  models at ``/chat/completions``.

So a model id this build has not reviewed is ``UNKNOWN`` and is not dispatchable,
rather than being guessed onto a default protocol.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class OpenCodeGoProtocol(str, Enum):
    """Upstream endpoint shape an OpenCode Go model is served on."""

    CHAT_COMPLETIONS = "chat_completions"
    MESSAGES = "messages"
    RESPONSES = "responses"
    #: Returned by the live listing but absent from the reviewed docs table.
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class OpenCodeGoModelProfile:
    protocol: OpenCodeGoProtocol
    #: Go docs Privacy table records prompt/completion training and non-ZDR
    #: retention for this model. Never auto-enable one of these.
    privacy_sensitive: bool = False


#: Protocols this build can actually dispatch. Everything else is advertised as
#: unavailable rather than silently substituted onto a protocol we do implement.
SUPPORTED_PROTOCOLS: frozenset[OpenCodeGoProtocol] = frozenset({OpenCodeGoProtocol.CHAT_COMPLETIONS})

_CHAT = OpenCodeGoProtocol.CHAT_COMPLETIONS
_MESSAGES = OpenCodeGoProtocol.MESSAGES
_RESPONSES = OpenCodeGoProtocol.RESPONSES

#: Transcribed from the official https://opencode.ai/docs/go endpoint table.
OPENCODE_GO_MODEL_PROTOCOLS: dict[str, OpenCodeGoModelProfile] = {
    # https://opencode.ai/zen/go/v1/chat/completions  (@ai-sdk/openai-compatible)
    "glm-5.3-flash": OpenCodeGoModelProfile(_CHAT),
    "glm-5.3": OpenCodeGoModelProfile(_CHAT),
    "glm-5.2": OpenCodeGoModelProfile(_CHAT),
    "glm-5.1": OpenCodeGoModelProfile(_CHAT),
    "kimi-k3": OpenCodeGoModelProfile(_CHAT),
    "kimi-k2.7-code": OpenCodeGoModelProfile(_CHAT),
    "kimi-k2.6": OpenCodeGoModelProfile(_CHAT),
    "longcat-2.0": OpenCodeGoModelProfile(_CHAT),
    "deepseek-v4.1-flash": OpenCodeGoModelProfile(_CHAT),
    "deepseek-v4-pro": OpenCodeGoModelProfile(_CHAT),
    "deepseek-v4-flash": OpenCodeGoModelProfile(_CHAT),
    "deepseek-v4-flash-vision-exp": OpenCodeGoModelProfile(_CHAT),
    "mimo-v2.5": OpenCodeGoModelProfile(_CHAT),
    "mimo-v2.5-pro": OpenCodeGoModelProfile(_CHAT),
    "hy4-preview": OpenCodeGoModelProfile(_CHAT),
    "hy3": OpenCodeGoModelProfile(_CHAT),
    # https://opencode.ai/zen/go/v1/messages  (@ai-sdk/anthropic)
    "minimax-m3": OpenCodeGoModelProfile(_MESSAGES),
    "minimax-m2.7": OpenCodeGoModelProfile(_MESSAGES),
    "minimax-m2.5": OpenCodeGoModelProfile(_MESSAGES),
    "qwen3.8-max": OpenCodeGoModelProfile(_MESSAGES),
    "qwen3.8-flash": OpenCodeGoModelProfile(_MESSAGES),
    "qwen3.7-max": OpenCodeGoModelProfile(_MESSAGES),
    "qwen3.7-plus": OpenCodeGoModelProfile(_MESSAGES),
    "qwen3.6-plus": OpenCodeGoModelProfile(_MESSAGES),
    # https://opencode.ai/zen/go/v1/responses  (@ai-sdk/openai)
    "grok-4.6": OpenCodeGoModelProfile(_RESPONSES),
    "gpt-5.6-luna": OpenCodeGoModelProfile(_RESPONSES),
    # Go docs Privacy table: "Model training: Yes", "Data retention: Not ZDR",
    # availability limited by Meta's Geographic Use Policy. Both are
    # ``/responses`` models, so they are already outside this build's dispatch
    # scope; the flag exists so a later scope expansion cannot quietly enable
    # them without a deliberate decision.
    "muse-spark-1.3-contributor": OpenCodeGoModelProfile(_RESPONSES, privacy_sensitive=True),
    "muse-spark-1.2-contributor": OpenCodeGoModelProfile(_RESPONSES, privacy_sensitive=True),
}

_UNKNOWN_PROFILE = OpenCodeGoModelProfile(OpenCodeGoProtocol.UNKNOWN)


def normalize_opencode_go_model_id(model: str) -> str:
    return model.strip().lower()


def opencode_go_model_profile(model: str) -> OpenCodeGoModelProfile:
    """Return the reviewed profile for ``model``, or the UNKNOWN profile."""

    return OPENCODE_GO_MODEL_PROTOCOLS.get(normalize_opencode_go_model_id(model), _UNKNOWN_PROFILE)


def opencode_go_model_protocol(model: str) -> OpenCodeGoProtocol:
    return opencode_go_model_profile(model).protocol


def is_opencode_go_model_supported(model: str) -> bool:
    """Can this build dispatch ``model`` to a protocol it actually implements?

    A privacy-sensitive model is never reported supported, independently of its
    protocol, so a future protocol expansion cannot make one dispatchable as a
    side effect.
    """

    profile = opencode_go_model_profile(model)
    if profile.privacy_sensitive:
        return False
    return profile.protocol in SUPPORTED_PROTOCOLS


def supported_opencode_go_model_ids() -> tuple[str, ...]:
    """Every reviewed id this build can dispatch, in map order."""

    return tuple(model_id for model_id in OPENCODE_GO_MODEL_PROTOCOLS if is_opencode_go_model_supported(model_id))


def unsupported_model_message(model: str) -> str:
    """Client-facing explanation for a model this build will not dispatch.

    Names the upstream protocol rather than saying "unknown model", because the
    model may well exist and work in the OpenCode CLI - it is *this* integration
    that does not speak its endpoint yet.
    """

    profile = opencode_go_model_profile(model)
    normalized = normalize_opencode_go_model_id(model)
    if profile.protocol is OpenCodeGoProtocol.UNKNOWN:
        return (
            f"Model '{normalized}' is not a reviewed OpenCode Go model in this build. "
            "Only models on the OpenCode Go /chat/completions endpoint are supported."
        )
    if profile.privacy_sensitive:
        return (
            f"Model '{normalized}' is not enabled: OpenCode Go documents it as training on "
            "prompts and completions without zero data retention."
        )
    return (
        f"Model '{normalized}' is served by OpenCode Go on the /{profile.protocol.value.replace('_', '/')} "
        "endpoint, which this build does not support. Only /chat/completions models are supported."
    )
