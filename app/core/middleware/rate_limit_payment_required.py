from __future__ import annotations

import logging
from typing import Final

from fastapi import FastAPI
from starlette._utils import get_route_path
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.auth.request_api_key import get_authenticated_api_key
from app.core.resilience.overload import is_proxy_path

logger = logging.getLogger(__name__)

RATE_LIMITED_STATUS: Final = 429
PAYMENT_REQUIRED_STATUS: Final = 402


class RateLimitPaymentRequiredMiddleware:
    """Send 402 instead of 429 to API keys with ``rate_limit_as_payment_required``.

    Some clients (the Vercel AI SDK, and agents built on it such as Kodus)
    retry every 429 several times with a short backoff and ignore a long
    ``Retry-After``. When the account pool is exhausted that only burns time
    and delays the client's own model fallback. Those clients treat 402 as
    terminal, so an operator can opt a key in and the client fails over at once.

    Only the status line changes. The body and every header, including
    ``Retry-After``, pass through untouched, and request logs keep the original
    error. Pure ASGI, so streamed responses are relayed without buffering.
    Responses decided before the key is authenticated (admission control in
    outer middleware) are never seen here and keep their status.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not is_proxy_path(get_route_path(scope)):
            await self.app(scope, receive, send)
            return

        async def send_with_key_policy(message: Message) -> None:
            if message["type"] == "http.response.start" and message["status"] == RATE_LIMITED_STATUS:
                api_key = get_authenticated_api_key(scope)
                if api_key is not None and api_key.rate_limit_as_payment_required:
                    logger.info(
                        "api_key_rate_limit_as_payment_required api_key_id=%s path=%s status=%s->%s",
                        api_key.id,
                        get_route_path(scope),
                        RATE_LIMITED_STATUS,
                        PAYMENT_REQUIRED_STATUS,
                    )
                    message = {**message, "status": PAYMENT_REQUIRED_STATUS}
            await send(message)

        await self.app(scope, receive, send_with_key_policy)


def add_rate_limit_payment_required_middleware(app: FastAPI) -> None:
    app.add_middleware(RateLimitPaymentRequiredMiddleware)
