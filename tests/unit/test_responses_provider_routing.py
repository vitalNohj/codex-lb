from __future__ import annotations

import json
from dataclasses import replace

import pytest
from starlette.responses import JSONResponse

from app.core.clients.claude_sidecar import SidecarPrefix
from app.core.openai.model_registry import ReasoningLevel, UpstreamModel, get_model_registry
from app.core.utils.stream_close import ClosingStreamingResponse
from app.modules.proxy.responses_provider_dispatch import (
    codex_serves_model,
    non_http_responses_model_rejection,
    translate_chat_response_to_responses,
)
from app.modules.proxy.sidecar_routing import SidecarRoutingEntry

pytestmark = pytest.mark.unit


def _model(slug: str) -> UpstreamModel:
    return UpstreamModel(
        slug=slug,
        display_name=slug,
        description=slug,
        context_window=128000,
        input_modalities=("text",),
        supported_reasoning_levels=(ReasoningLevel(effort="medium", description="medium"),),
        default_reasoning_level="medium",
        supports_reasoning_summaries=False,
        support_verbosity=False,
        default_verbosity=None,
        prefer_websockets=False,
        supports_parallel_tool_calls=True,
        supported_in_api=True,
        minimal_client_version=None,
        priority=0,
        available_in_plans=frozenset({"plus"}),
        raw={},
    )


@pytest.fixture
async def registry_state():
    registry = get_model_registry()
    state = await registry.export_state()
    try:
        yield registry
    finally:
        await registry.import_state(state, content_hash="restore-responses-routing")


async def test_codex_serves_model_is_open_until_catalogs_are_authoritative(registry_state) -> None:
    registry = registry_state
    await registry.clear()
    assert codex_serves_model("nvidia/nemotron-3-content-safety") is True
    assert codex_serves_model("gpt-5.1") is True


async def test_codex_serves_model_uses_authoritative_catalog(registry_state) -> None:
    registry = registry_state
    await registry.clear()
    served = _model("gpt-5.4")
    await registry.update(
        {"plus": [served]},
        per_account_results={"acct": ("plus", [served])},
        active_account_plans={"acct": "plus"},
    )
    snapshot = registry.get_snapshot()
    assert snapshot is not None and snapshot.account_catalogs_authoritative

    assert codex_serves_model("gpt-5.4") is True
    assert codex_serves_model("GPT-5.4") is True
    assert codex_serves_model("nvidia/nemotron-3-content-safety") is False
    assert codex_serves_model("gpt-5.1") is False


async def test_codex_serves_model_ignores_an_empty_authoritative_catalog(registry_state) -> None:
    registry = registry_state
    await registry.clear()
    served = _model("gpt-5.4")
    await registry.update(
        {"plus": [served]},
        per_account_results={"acct": ("plus", [served])},
        active_account_plans={"acct": "plus"},
    )
    snapshot = registry.get_snapshot()
    assert snapshot is not None
    registry._snapshot = replace(snapshot, models={})

    assert codex_serves_model("nvidia/nemotron-3-content-safety") is True


def test_translate_chat_json_and_errors() -> None:
    completion = JSONResponse(
        {
            "id": "chatcmpl-1",
            "choices": [{"message": {"role": "assistant", "content": "hi"}}],
            "usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3},
        }
    )
    translated = translate_chat_response_to_responses(completion, model="requested-model")
    body = json.loads(translated.body)
    assert body["object"] == "response"
    assert body["model"] == "requested-model"
    assert body["output"][0]["content"][0]["text"] == "hi"

    error = JSONResponse(
        {"error": {"message": "nope", "type": "invalid_request_error", "code": "bad"}},
        status_code=400,
    )
    assert translate_chat_response_to_responses(error, model="requested-model") is error


async def test_translate_chat_sse_emits_one_done() -> None:
    async def chunks():
        yield b'data: {"choices":[{"delta":{"content":"hi"}}]}\n\n'
        yield b"data: [DONE]\n\n"

    source = ClosingStreamingResponse(chunks(), media_type="text/event-stream", settling=None)
    translated = translate_chat_response_to_responses(source, model="requested-model")
    parts: list[bytes] = []
    async for part in translated.body_iterator:
        parts.append(part if isinstance(part, bytes) else part.encode("utf-8"))
    text = b"".join(parts)
    assert b"hi" in text
    assert text.count(b"data: [DONE]") == 1


async def test_non_http_rejection_blocks_sidecar_and_unknown(monkeypatch, registry_state) -> None:
    registry = registry_state

    async def entries() -> tuple[SidecarRoutingEntry, ...]:
        return (
            SidecarRoutingEntry(
                provider="claude",
                prefixes=(SidecarPrefix(prefix="claude", strip=False),),
                full_models=("claude-opus-4-7",),
            ),
        )

    monkeypatch.setattr("app.modules.proxy.api._enabled_sidecar_routing_entries", entries)
    await registry.clear()
    served = _model("gpt-5.4")
    await registry.update(
        {"plus": [served]},
        per_account_results={"acct": ("plus", [served])},
        active_account_plans={"acct": "plus"},
    )

    sidecar = await non_http_responses_model_rejection("claude-opus-4-7", source_owned=False)
    assert sidecar is not None
    assert sidecar[0] == 400
    assert sidecar[1]["error"]["code"] == "model_requires_responses_http"

    owned = await non_http_responses_model_rejection("claude-opus-4-7", source_owned=True)
    assert owned is not None and owned[0] == 400

    missing = await non_http_responses_model_rejection("nvidia/nemotron-3-content-safety", source_owned=False)
    assert missing is not None
    assert missing[0] == 404
    assert missing[1]["error"]["code"] == "model_not_found"

    source = await non_http_responses_model_rejection("nvidia/nemotron-3-content-safety", source_owned=True)
    assert source is None
    assert await non_http_responses_model_rejection("gpt-5.4", source_owned=False) is None
