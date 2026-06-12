from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from starlette.requests import Request

from app.modules.api_keys.service import ApiKeyData
from app.modules.proxy.api import _trace_summarize_control_payload


def _request_with_body(body: bytes) -> Request:
    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/backend-api/codex/memories/trace_summarize",
            "headers": [(b"content-type", b"application/json")],
        },
        receive,
    )


def _api_key(**overrides: object) -> ApiKeyData:
    values = {
        "id": "key_trace_summarize",
        "name": "trace summarize",
        "key_prefix": "sk-trace",
        "allowed_models": ["gpt-5.5"],
        "enforced_model": None,
        "enforced_reasoning_effort": "high",
        "enforced_service_tier": "priority",
        "expires_at": None,
        "is_active": True,
        "created_at": datetime(2026, 1, 1, tzinfo=UTC),
        "last_used_at": None,
    }
    values.update(overrides)
    return ApiKeyData(**values)


@pytest.mark.asyncio
async def test_trace_summarize_normalizes_model_policy_fields() -> None:
    request = _request_with_body(
        json.dumps(
            {
                "model": "gpt-5.5-low-fast",
                "raw_memories": [{"id": "mem_1", "text": "Keep this"}],
                "metadata": {"source": "cursor"},
            }
        ).encode("utf-8")
    )

    body = await _trace_summarize_control_payload(request, _api_key())

    assert json.loads(body) == {
        "model": "gpt-5.5",
        "raw_memories": [{"id": "mem_1", "text": "Keep this"}],
        "metadata": {"source": "cursor"},
        "reasoning": {"effort": "high"},
        "service_tier": "priority",
    }


@pytest.mark.asyncio
async def test_trace_summarize_without_model_preserves_original_body() -> None:
    original = b'{"raw_memories":[{"id":"mem_1"}],"metadata":{"source":"cursor"}}'
    request = _request_with_body(original)

    body = await _trace_summarize_control_payload(request, _api_key())

    assert body == original


@pytest.mark.asyncio
async def test_trace_summarize_non_json_preserves_original_body() -> None:
    original = b"not-json"
    request = _request_with_body(original)

    body = await _trace_summarize_control_payload(request, _api_key())

    assert body == original
