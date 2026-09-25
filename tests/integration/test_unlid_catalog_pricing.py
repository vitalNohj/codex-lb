"""An OpenAI-compatible Unlid listing supplies a durable request-log cost."""

from __future__ import annotations

import json

import pytest
from sqlalchemy import select

from app.core.clients.claude_sidecar import SidecarModel
from app.core.usage.external_pricing import service as pricing_service
from app.core.usage.external_pricing.service import get_lookup_coordinator
from app.db.models import CostSource, ExternalModelPrice, ExternalPriceStatus, RequestLog
from app.db.session import SessionLocal

pytestmark = pytest.mark.integration

MODEL = "glm-5.3-flash-uncensored"
ENDPOINT_ID = "b00c79c6-5349-4726-8e33-e2cdc6e6ca95"
PROVIDER = f"openai_compat:{ENDPOINT_ID}"
LISTING = {
    "id": MODEL,
    "owned_by": "unlid",
    "unlid": {
        "pricing": {
            "input_usd_per_m": 0.42,
            "output_usd_per_m": 1.68,
            "cached_input_usd_per_m": 0.216,
            "checked_at": "2026-09-10",
        }
    },
}


class _ChatClient:
    def __init__(self, config):
        self.config = config

    async def list_models_cached(self):
        return [SidecarModel(id=MODEL, raw=LISTING, owned_by="unlid")]

    async def chat_completion(self, payload):
        assert payload["model"] == MODEL
        return {
            "id": "chatcmpl-unlid",
            "object": "chat.completion",
            "model": MODEL,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "pong"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 13, "completion_tokens": 64, "total_tokens": 77},
            "unlid": {"cost_usd": 0.00011298},
        }


class _ModelsResponse:
    status = 200

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def text(self):
        return json.dumps({"object": "list", "data": [LISTING]})


class _ModelsSession:
    def get(self, url, *, headers, timeout):
        assert url == "https://api.unlid.ai/v1/models"
        return _ModelsResponse()


class _ModelsLease:
    async def __aenter__(self):
        return _ModelsSession()

    async def __aexit__(self, exc_type, exc, tb):
        return None


@pytest.mark.asyncio
async def test_unlid_catalog_rates_resolve_and_price_a_second_chat_request(async_client, monkeypatch) -> None:
    async def _no_reference():
        return None

    monkeypatch.setattr(pricing_service, "_load_reference_catalog", _no_reference)
    monkeypatch.setattr("app.core.clients.openai_compat_sidecar.lease_http_session", _ModelsLease)
    monkeypatch.setattr("app.modules.proxy.api.get_openai_compat_sidecar_client", lambda config: _ChatClient(config))
    monkeypatch.setattr("app.modules.proxy.api.OpenAICompatSidecarClient", lambda config: _ChatClient(config))

    settings = await async_client.put(
        "/api/settings",
        json={
            "openaiCompatEndpoints": [
                {
                    "id": ENDPOINT_ID,
                    "name": "Unlid",
                    "enabled": True,
                    "baseUrl": "https://api.unlid.ai/v1",
                    "modelPrefixes": [],
                    "fullModels": [MODEL],
                }
            ]
        },
    )
    assert settings.status_code == 200, settings.text

    async def _request():
        response = await async_client.post(
            "/v1/chat/completions",
            json={"model": MODEL, "messages": [{"role": "user", "content": "Hello"}]},
        )
        assert response.status_code == 200, response.text
        assert response.json()["choices"][0]["message"]["content"] == "pong"

    await _request()
    await get_lookup_coordinator().drain()
    await _request()
    await get_lookup_coordinator().drain()

    async with SessionLocal() as session:
        prices = list((await session.execute(select(ExternalModelPrice))).scalars().all())
        logs = sorted((await session.execute(select(RequestLog))).scalars().all(), key=lambda log: log.id)
    assert len(prices) == 1
    assert prices[0].provider == PROVIDER
    assert prices[0].status == ExternalPriceStatus.RESOLVED.value
    assert prices[0].catalog_source == PROVIDER
    assert prices[0].input_per_1m == pytest.approx(0.42)
    assert prices[0].output_per_1m == pytest.approx(1.68)
    assert len(logs) == 2
    assert logs[0].cost_usd is None
    assert logs[0].price_status == ExternalPriceStatus.PENDING.value
    assert logs[1].cost_usd == pytest.approx(0.00011298)
    assert logs[1].cost_source == CostSource.CATALOG_CALCULATED.value
    assert logs[1].price_status == ExternalPriceStatus.RESOLVED.value
