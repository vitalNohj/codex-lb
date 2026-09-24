"""Single-probe execution and verdict classification.

The error model is deliberately one-sided. Only a clean HTTP 200 carrying a
well-formed ``choices[0].message`` yields a verdict:

* non-empty ``content`` -> ``passed``
* empty ``content``     -> ``failed``

Everything else (429, 5xx, transport error, timeout, a 200 with no usable
message) is ``inconclusive``. Inconclusive never counts against a model; the
runner just retries later. Error strings are never parsed for meaning.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal, Protocol

from app.core.clients.claude_sidecar import SidecarModel
from app.core.clients.openrouter_sidecar import OpenRouterSidecarError, OpenRouterSidecarUnavailableError
from app.core.clients.orcarouter_sidecar import (
    OrcaRouterSidecarError,
    OrcaRouterSidecarUnavailableError,
    sanitize_orcarouter_message,
)
from app.core.utils.json_guards import JsonValue, is_json_mapping
from app.modules.free_model_discovery.limits import (
    LimitScope,
    RateLimitEvidence,
    classify_scope,
    evidence_from_response,
)

PROBE_PROMPT = "Reply with exactly: ok"
PROBE_MAX_TOKENS = 16
# Reasoning is a diagnostic only. A block longer than this counts as "the
# model actually reasoned" in the run view; it never affects the verdict.
REASONING_DIAGNOSTIC_MIN_CHARS = 3
_OUTCOME_MAX_CHARS = 255

ProbeVerdict = Literal["passed", "failed", "inconclusive"]


class ChatCompletionClient(Protocol):
    async def chat_completion(self, payload: Mapping[str, JsonValue]) -> JsonValue: ...


class SidecarProbeClient(ChatCompletionClient, Protocol):
    async def list_models(self) -> list[SidecarModel]: ...


@dataclass(frozen=True, slots=True)
class ProbeResult:
    verdict: ProbeVerdict
    http_status: int | None
    outcome: str
    content_chars: int | None = None
    content_ok_match: bool | None = None
    reasoning_chars: int | None = None
    retry_after_seconds: float | None = None
    # What the vendor actually attributed the rejection to. ``unknown`` unless
    # the documented contract established it - a 429 alone never does.
    limit_scope: LimitScope = "unknown"
    evidence: RateLimitEvidence = field(default_factory=RateLimitEvidence)

    @property
    def rate_limited(self) -> bool:
        return self.http_status == 429

    @property
    def shared_limit(self) -> bool:
        """Only an explicitly vendor-attributed provider/account-wide limit."""

        return self.limit_scope == "shared"


def build_probe_payload(model_id: str) -> dict[str, JsonValue]:
    return {
        "model": model_id,
        "messages": [{"role": "user", "content": PROBE_PROMPT}],
        "max_tokens": PROBE_MAX_TOKENS,
        "stream": False,
    }


def redact_provider_text(message: str, *, api_key: str | None) -> str:
    """Strip provider credentials out of upstream-controlled diagnostic text.

    Discovery persists this text to ``last_outcome`` and serves it from the run
    API, so it lands in the dashboard exactly like the surfaces the provider
    clients already guard. An upstream that echoes the ``Authorization`` header
    must not leak the key on any of them.

    Reuses the OrcaRouter sanitizer for both providers deliberately: it is the
    project's existing credential-aware contract, it redacts the configured key
    as a whole token whatever its shape, and its unconditional ``Bearer``/
    ``sk-`` patterns also catch a key that is no longer the configured one.
    OpenRouter ships no sanitizer of its own, so the alternative would be a
    second copy that can drift.
    """

    return sanitize_orcarouter_message(message, api_key=api_key)


async def probe_model(client: ChatCompletionClient, model_id: str, *, api_key: str | None = None) -> ProbeResult:
    """Probe one model. ``api_key`` is the provider credential whose appearance
    in upstream error text must be redacted before it is persisted."""

    try:
        body = await client.chat_completion(build_probe_payload(model_id))
    except (OpenRouterSidecarUnavailableError, OrcaRouterSidecarUnavailableError) as exc:
        return ProbeResult(
            verdict="inconclusive",
            http_status=None,
            # Redact before clipping: clipping a secret still persists its prefix.
            outcome=_clip(redact_provider_text(f"transport: {exc.message}", api_key=api_key)),
        )
    except (OpenRouterSidecarError, OrcaRouterSidecarError) as exc:
        evidence = evidence_from_response(headers=getattr(exc, "rate_limit_headers", None), body=exc.body)
        scope = classify_scope(evidence)
        return ProbeResult(
            verdict="inconclusive",
            http_status=exc.status_code,
            outcome=_clip(redact_provider_text(f"http {exc.status_code}: {exc.message}", api_key=api_key)),
            retry_after_seconds=evidence.retry_after_seconds,
            limit_scope=scope,
            evidence=evidence,
        )
    return classify_completion(body, api_key=api_key)


def classify_completion(body: JsonValue, *, api_key: str | None = None) -> ProbeResult:
    """Classify a 200 response body. Malformed bodies are inconclusive.

    ``api_key`` redacts upstream-controlled text. Routers stuff throttles and
    auth failures into a 200 envelope with an ``error`` key, so this path also
    persists provider text and needs the same guarantee as the exception paths;
    covering only exceptions left the echoed-credential case open.
    """

    if not is_json_mapping(body):
        return ProbeResult(verdict="inconclusive", http_status=200, outcome="200 without a JSON object body")
    # Some routers stuff a throttle into a 200 envelope with an ``error`` key
    # and no choices. That is not a verdict on the model.
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices:
        # OpenRouter documents that a provider failing after headers were sent
        # yields "a 200 OK whose JSON body holds only an error object and no
        # choices", so scope evidence has to be read here too - not only on
        # the exception paths.
        evidence = evidence_from_response(headers=None, body=body)
        return ProbeResult(
            verdict="inconclusive",
            http_status=200,
            # Redact before clipping: clipping a secret still persists a prefix.
            outcome=_clip(redact_provider_text(_describe_missing_choices(body), api_key=api_key)),
            retry_after_seconds=evidence.retry_after_seconds,
            limit_scope=classify_scope(evidence),
            evidence=evidence,
        )
    first = choices[0]
    if not is_json_mapping(first):
        return ProbeResult(verdict="inconclusive", http_status=200, outcome="200 with a malformed first choice")
    message = first.get("message")
    if not is_json_mapping(message):
        return ProbeResult(verdict="inconclusive", http_status=200, outcome="200 with no message in first choice")
    content = _content_text(message.get("content"))
    if content is None:
        return ProbeResult(verdict="inconclusive", http_status=200, outcome="200 with a malformed message content")
    reasoning_chars = _reasoning_chars(message)
    stripped = content.strip()
    if not stripped:
        return ProbeResult(
            verdict="failed",
            http_status=200,
            outcome="200 with empty content",
            content_chars=0,
            content_ok_match=False,
            reasoning_chars=reasoning_chars,
        )
    return ProbeResult(
        verdict="passed",
        http_status=200,
        outcome="200 with content",
        content_chars=len(stripped),
        content_ok_match="ok" in stripped.lower(),
        reasoning_chars=reasoning_chars,
    )


def _content_text(content: JsonValue) -> str | None:
    """Accept a string or an OpenAI content-part list. Anything else is malformed."""

    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif is_json_mapping(part):
                text = part.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "".join(parts)
    return None


def _reasoning_chars(message: Mapping[str, JsonValue]) -> int | None:
    """Read the reasoning block defensively; field name varies by provider."""

    for key in ("reasoning_content", "reasoning"):
        value = message.get(key)
        if isinstance(value, str):
            return len(value.strip())
        if isinstance(value, list):
            text = _content_text(value)
            return len(text.strip()) if text is not None else None
    return None


def _describe_missing_choices(body: Mapping[str, JsonValue]) -> str:
    error = body.get("error")
    if is_json_mapping(error):
        message = error.get("message")
        if isinstance(message, str) and message:
            return f"200 without choices: {message}"
    return "200 without choices"


def _clip(text: str) -> str:
    collapsed = " ".join(text.split())
    if len(collapsed) <= _OUTCOME_MAX_CHARS:
        return collapsed
    return collapsed[: _OUTCOME_MAX_CHARS - 3] + "..."
