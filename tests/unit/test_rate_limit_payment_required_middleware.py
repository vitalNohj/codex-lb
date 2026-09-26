from __future__ import annotations

from datetime import UTC, datetime

import pytest
from starlette.types import Message, Receive, Scope, Send

from app.core.auth.request_api_key import get_authenticated_api_key, set_authenticated_api_key
from app.core.middleware.rate_limit_payment_required import RateLimitPaymentRequiredMiddleware
from app.modules.api_keys.service import ApiKeyData

pytestmark = pytest.mark.unit


def _key(key_id: str, rate_limit_as_payment_required: bool) -> ApiKeyData:
    return ApiKeyData(
        id=key_id,
        name=key_id,
        key_prefix="sk-clb-test",
        allowed_models=None,
        enforced_model=None,
        enforced_reasoning_effort=None,
        enforced_service_tier=None,
        expires_at=None,
        is_active=True,
        created_at=datetime(2026, 9, 25, tzinfo=UTC),
        last_used_at=None,
        rate_limit_as_payment_required=rate_limit_as_payment_required,
    )


def _route(*, status: int, api_key: ApiKeyData | None, chunks: tuple[bytes, ...] = (b'{"error":{}}',)):
    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        del receive
        if api_key is not None:
            set_authenticated_api_key(scope, api_key)
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [(b"content-type", b"application/json"), (b"retry-after", b"300")],
            }
        )
        for index, chunk in enumerate(chunks):
            await send({"type": "http.response.body", "body": chunk, "more_body": index < len(chunks) - 1})

    return app


async def _run(app, *, path: str = "/v1/chat/completions", scope_type: str = "http") -> list[Message]:
    sent: list[Message] = []

    async def receive() -> Message:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: Message) -> None:
        sent.append(message)

    scope: Scope = {"type": scope_type, "path": path, "root_path": "", "headers": []}
    await RateLimitPaymentRequiredMiddleware(app)(scope, receive, send)
    return sent


@pytest.mark.asyncio
async def test_flagged_key_429_becomes_402_with_headers_and_body_unchanged() -> None:
    body = b'{"error":{"code":"usage_limit_reached","message":"Rate limit exceeded. Try again in 300s"}}'
    sent = await _run(_route(status=429, api_key=_key("k1", True), chunks=(body[:10], body[10:])))

    assert sent[0]["status"] == 402
    assert sent[0]["headers"] == [(b"content-type", b"application/json"), (b"retry-after", b"300")]
    assert b"".join(message["body"] for message in sent[1:]) == body
    assert [message.get("more_body") for message in sent[1:]] == [True, False]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "api_key"),
    [
        (429, _key("k-off", False)),
        (429, None),
        (200, _key("k-on", True)),
        (400, _key("k-on", True)),
        (503, _key("k-on", True)),
    ],
)
async def test_status_passes_through_unless_flagged_429(status: int, api_key: ApiKeyData | None) -> None:
    sent = await _run(_route(status=status, api_key=api_key))

    assert sent[0]["status"] == status


@pytest.mark.asyncio
async def test_non_proxy_paths_are_not_rewritten() -> None:
    sent = await _run(_route(status=429, api_key=_key("k1", True)), path="/api/settings")

    assert sent[0]["status"] == 429


@pytest.mark.asyncio
async def test_backend_api_proxy_path_is_rewritten() -> None:
    sent = await _run(_route(status=429, api_key=_key("k1", True)), path="/backend-api/codex/responses")

    assert sent[0]["status"] == 402


def test_authenticated_api_key_round_trips_on_scope_state() -> None:
    scope: Scope = {"type": "http"}
    assert get_authenticated_api_key(scope) is None

    key = _key("k1", True)
    set_authenticated_api_key(scope, key)

    assert get_authenticated_api_key(scope) is key
    assert scope["state"]["codex_lb_authenticated_api_key"] is key
