from __future__ import annotations

import asyncio
import importlib
from collections.abc import AsyncIterator
from types import ModuleType, SimpleNamespace

import pytest

from app.modules.proxy.external_pricing_logging import ExternalRequestCost


class _StreamContext:
    def __init__(self, chunks: AsyncIterator[bytes]) -> None:
        self._chunks = chunks

    async def __aenter__(self) -> AsyncIterator[bytes]:
        return self._chunks

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None


class _StreamClient:
    def __init__(self, mode: str, event: bytes) -> None:
        self.mode = mode
        self.event = event
        self.config = SimpleNamespace(api_key="test-key")

    def stream_chat_completion(self, payload: object) -> _StreamContext:
        return _StreamContext(self._chunks())

    async def _chunks(self) -> AsyncIterator[bytes]:
        yield self.event
        if self.mode == "transport_error":
            raise RuntimeError("transport failed")
        if self.mode == "cancellation":
            raise asyncio.CancelledError
        if self.mode == "normal":
            yield b"data: [DONE]\n\n"


class _ErrorClient:
    def __init__(self, error: Exception) -> None:
        self.error = error
        self.config = SimpleNamespace(default_reasoning_effort=None, api_key="test-key")

    async def chat_completion(self, payload: object) -> object:
        raise self.error


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "module_name,iterator_name,finalize_name,log_name",
    [
        (
            "app.modules.proxy.openrouter_sidecar_dispatch",
            "_openrouter_stream_iterator",
            "_finalize_or_release_openrouter_reservation",
            "_log_openrouter_request",
        ),
        (
            "app.modules.proxy.orcarouter_sidecar_dispatch",
            "_orcarouter_stream_iterator",
            "_finalize_or_release_orcarouter_reservation",
            "_log_orcarouter_request",
        ),
    ],
)
@pytest.mark.parametrize("mode", ["normal", "incomplete", "transport_error", "cancellation", "disconnect"])
@pytest.mark.parametrize(
    ("event", "has_complete_usage"),
    [
        (b'data: {"usage":{"cost":0.01}}\n\n', False),
        (b'data: {"usage":{"prompt_tokens":10,"cost":0.01}}\n\n', False),
        (
            b'data: {"usage":{"prompt_tokens":0,"completion_tokens":0,"cost":0.01}}\n\n',
            True,
        ),
        (
            b'data: {"usage":{"prompt_tokens":2147483648,"completion_tokens":0,"cost":0.01}}\n\n',
            False,
        ),
        (
            b'data: {"usage":{"cost":0.01}}\n\ndata: {"usage":{"cost":-1}}\n\n',
            False,
        ),
        (
            b'data: {"usage":{"cost":0.01}}\n\ndata: {"usage":{"cost":NaN}}\n\n',
            False,
        ),
        (
            b'data: {"usage":{"cost":0.01}}\n\ndata: {"usage":{"cost":1e308}}\n\n',
            False,
        ),
    ],
)
async def test_reported_stream_charge_is_settled_once_for_every_termination(
    monkeypatch: pytest.MonkeyPatch,
    module_name: str,
    iterator_name: str,
    finalize_name: str,
    log_name: str,
    mode: str,
    event: bytes,
    has_complete_usage: bool,
) -> None:
    module: ModuleType = importlib.import_module(module_name)
    finalized: list[dict[str, object]] = []
    logged: list[dict[str, object]] = []

    async def _no_catalog_price(**kwargs: object) -> tuple[None, None]:
        return None, None

    async def _finalize(*args: object, **kwargs: object) -> None:
        finalized.append(kwargs)

    async def _log(**kwargs: object) -> None:
        logged.append(kwargs)

    monkeypatch.setattr(
        "app.modules.proxy.external_pricing_logging.calculated_cost_for_request",
        _no_catalog_price,
    )
    monkeypatch.setattr(module, finalize_name, _finalize)
    monkeypatch.setattr(module, log_name, _log)

    stream = getattr(module, iterator_name)(
        {},
        api_key=None,
        reservation=SimpleNamespace(reservation_id="reservation-1"),
        model="vendor/model-x",
        started_at=0,
        client=_StreamClient(mode, event),
    )

    if mode == "disconnect":
        await anext(stream)
        await stream.aclose()
    elif mode == "transport_error":
        with pytest.raises(RuntimeError, match="transport failed"):
            async for _ in stream:
                pass
    elif mode == "cancellation":
        with pytest.raises(asyncio.CancelledError):
            async for _ in stream:
                pass
    else:
        async for _ in stream:
            pass

    assert len(finalized) == 1
    assert len(logged) == 1
    finalized_cost = finalized[0]["cost"]
    logged_cost = logged[0]["cost"]
    assert isinstance(finalized_cost, ExternalRequestCost)
    assert finalized_cost is logged_cost
    assert finalized_cost.cost_usd == pytest.approx(0.01)
    assert finalized_cost.cost_source == "upstream_billed"
    if mode == "normal" and has_complete_usage:
        assert finalized[0]["usage"] is not None
        assert logged[0]["usage"] is not None
    else:
        assert finalized[0]["usage"] is None
        assert logged[0]["usage"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "module_name,proxy_name,error_name,finalize_name,log_name",
    [
        (
            "app.modules.proxy.openrouter_sidecar_dispatch",
            "proxy_chat_to_openrouter",
            "OpenRouterSidecarError",
            "_finalize_or_release_openrouter_reservation",
            "_log_openrouter_request",
        ),
        (
            "app.modules.proxy.orcarouter_sidecar_dispatch",
            "proxy_chat_to_orcarouter",
            "OrcaRouterSidecarError",
            "_finalize_or_release_orcarouter_reservation",
            "_log_orcarouter_request",
        ),
    ],
)
async def test_reported_error_charge_is_settled_once(
    monkeypatch: pytest.MonkeyPatch,
    module_name: str,
    proxy_name: str,
    error_name: str,
    finalize_name: str,
    log_name: str,
) -> None:
    module: ModuleType = importlib.import_module(module_name)
    finalized: list[dict[str, object]] = []
    logged: list[dict[str, object]] = []

    async def _no_catalog_price(**kwargs: object) -> tuple[None, None]:
        return None, None

    async def _finalize(*args: object, **kwargs: object) -> None:
        finalized.append(kwargs)

    async def _log(**kwargs: object) -> None:
        logged.append(kwargs)

    monkeypatch.setattr(
        "app.modules.proxy.external_pricing_logging.calculated_cost_for_request",
        _no_catalog_price,
    )
    monkeypatch.setattr(module, finalize_name, _finalize)
    monkeypatch.setattr(module, log_name, _log)

    error = getattr(module, error_name)(
        429,
        "provider rejected request",
        body={"error": {"message": "provider rejected request"}, "usage": {"cost": 0.01}},
    )
    payload = module.ChatCompletionsRequest.model_validate(
        {"model": "vendor/model-x", "messages": [{"role": "user", "content": "hi"}]}
    )
    response = await getattr(module, proxy_name)(
        SimpleNamespace(),
        payload,
        effective_model="vendor/model-x",
        api_key=None,
        reservation=SimpleNamespace(reservation_id="reservation-1"),
        rate_limit_headers={},
        sse_keepalive_interval_seconds=1.0,
        client=_ErrorClient(error),
    )

    assert response.status_code == 429
    assert len(finalized) == 1
    assert len(logged) == 1
    finalized_cost = finalized[0]["cost"]
    assert isinstance(finalized_cost, ExternalRequestCost)
    assert finalized_cost is logged[0]["cost"]
    assert finalized_cost.cost_usd == pytest.approx(0.01)
    assert finalized_cost.cost_source == "upstream_billed"
    assert finalized[0]["usage"] is None
    assert logged[0]["usage"] is None
