"""Dispatch no longer rewrites a model id onto a CLIProxyAPI credential prefix."""

from __future__ import annotations

import pytest

from app.core.clients.claude_sidecar import ClaudeSidecarConfig, SidecarPrefix
from app.core.openai.chat_requests import ChatCompletionsRequest
from app.modules.proxy import claude_sidecar_dispatch
from app.modules.proxy.claude_sidecar_dispatch import build_sidecar_chat_payload

pytestmark = pytest.mark.unit


def test_sidecar_dispatch_does_not_select_a_credential_prefix() -> None:
    assert not hasattr(claude_sidecar_dispatch, "prepare_cliproxy_account_route")
    assert not hasattr(claude_sidecar_dispatch, "sidecar_operation_with_credential_failover")


def test_sidecar_chat_payload_forwards_the_resolved_model_id() -> None:
    payload = ChatCompletionsRequest.model_validate(
        {"model": "grok-4", "messages": [{"role": "user", "content": "hello"}]}
    )
    config = ClaudeSidecarConfig(
        enabled=True,
        base_url="http://127.0.0.1:8317",
        api_key="key",
        prefixes=(SidecarPrefix(prefix="claude", strip=False),),
        connect_timeout_seconds=8.0,
        request_timeout_seconds=600.0,
        models_cache_ttl_seconds=60.0,
    )

    forwarded = build_sidecar_chat_payload(payload, "grok-4", config)

    assert forwarded.body["model"] == "grok-4"
