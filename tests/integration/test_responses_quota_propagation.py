"""Exercise quota rejection through the public HTTP route and real bridge."""

import json
import time

import pytest

from app.modules.proxy import service as proxy_module
from tests.integration.test_http_responses_bridge import (
    _FakeBridgeUpstreamWebSocket,
    _FakeUpstreamMessage,
    _get_account,
    _import_account,
    _install_bridge_settings,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [True, False])
async def test_responses_quota_recovery_returns_honest_http_error(async_client, monkeypatch, stream):
    _install_bridge_settings(monkeypatch, enabled=True)
    account_id = await _import_account(async_client, "quota-evidence", "quota@example.com")
    account = await _get_account(account_id)
    message = "Usage limit reached. Try again in 300s"

    class QuotaUpstream(_FakeBridgeUpstreamWebSocket):
        async def send_text(self, text):
            self.sent_text.append(text)
            await self._messages.put(_FakeUpstreamMessage("text", text=json.dumps({
                "type": "error",
                "status": 429,
                "error": {
                    "code": "usage_limit_reached",
                    "type": "usage_limit_reached",
                    "message": message,
                    "resets_in_seconds": 300,
                },
            })))

    async def select(*args, **kwargs):
        return proxy_module.AccountSelection(account=account, error_message=None, error_code=None)

    async def fresh(self, target, **kwargs):
        return target

    async def connect(*args, **kwargs):
        return QuotaUpstream()

    monkeypatch.setattr(proxy_module.ProxyService, "_select_account_with_budget", select)
    monkeypatch.setattr(proxy_module.ProxyService, "_ensure_fresh_with_budget", fresh)
    monkeypatch.setattr(proxy_module, "connect_responses_websocket", connect)
    start = time.monotonic()
    response = await async_client.post("/v1/responses", json={
        "model": "gpt-4o", "input": "hello", "stream": stream,
        "prompt_cache_key": "quota-evidence",
    })
    elapsed = time.monotonic() - start
    print(json.dumps({
        "request": {"method": "POST", "path": "/v1/responses", "stream": stream},
        "upstream": {"code": "usage_limit_reached", "recovery_seconds": 300},
        "status": response.status_code,
        "retry_after": response.headers.get("retry-after"),
        "body": response.json(),
        "elapsed_seconds": round(elapsed, 3),
    }))
    assert response.status_code == 429
    assert response.json()["error"]["code"] == "usage_limit_reached"
    assert response.json()["error"]["message"] == message
    assert elapsed < 10
    assert response.headers.get("retry-after") == "300"
