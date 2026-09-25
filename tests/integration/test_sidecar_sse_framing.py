"""SSE framing on the OpenRouter, OrcaRouter, and OpenAI-compatible chat streams.

All three relay upstream chunks to the client untouched, so a client never sees
a framing problem. What breaks is the request's own accounting: usage and the
``[DONE]`` sentinel are read from *decoded* events, and a stream whose events
cannot be decoded settles with no usage and is logged
``*_stream_incomplete`` although it terminated correctly.

Real-world shapes driven through ``POST /v1/chat/completions``:

* **CRLF and CR framing.** The SSE spec allows CRLF, LF, and CR line endings.
  An observer that only splits on ``\\n\\n`` never finds an event boundary.
* **A multi-byte character split across chunks.** Chunk boundaries are byte
  offsets, so a character can straddle two chunks; decoding each chunk alone
  corrupts the JSON of the event that carries it.
* **Multi-line data under CRLF.** A single CRLF ends a line, not an event;
  splitting the event there leaves two halves that are not JSON.
* **Unicode line separators in data.** JSON strings may hold U+2028, U+2029,
  and U+0085 unescaped; ``str.splitlines`` breaks lines on them too.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass

import pytest
from sqlalchemy import select

from app.core.clients.claude_sidecar import SidecarPrefix
from app.core.clients.openai_compat_sidecar import OpenAICompatSidecarConfig
from app.core.clients.openrouter_sidecar import OpenRouterSidecarConfig
from app.core.clients.orcarouter_sidecar import OrcaRouterSidecarConfig
from app.core.config.settings import get_settings
from app.db.models import RequestLog
from app.db.session import SessionLocal

pytestmark = pytest.mark.integration

NON_ASCII = "café 日本語 🚀"


@dataclass(frozen=True, slots=True)
class _FakeModel:
    id: str
    created: int | None = 123
    owned_by: str | None = "test"
    raw: dict | None = None


class _ScriptedStream:
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks

    async def __aenter__(self):
        async def chunks():
            for chunk in self._chunks:
                yield chunk

        return chunks()

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


class _ScriptedSidecar:
    """Streams exactly the byte chunks it is given."""

    def __init__(self, config, model_id: str) -> None:
        self.config = config
        self.models = [_FakeModel(model_id)]
        self.chunks: list[bytes] = []

    async def list_models_cached(self):
        return self.models

    def stream_chat_completion(self, payload):
        return _ScriptedStream(self.chunks)


@dataclass(frozen=True, slots=True)
class _Provider:
    name: str
    model: str
    source: str
    settings: dict[str, object]
    install: Callable[[pytest.MonkeyPatch], _ScriptedSidecar]


def _install_openrouter(monkeypatch: pytest.MonkeyPatch) -> _ScriptedSidecar:
    monkeypatch.setenv("CODEX_LB_OPENROUTER_SIDECAR_ENABLED", "true")
    config = OpenRouterSidecarConfig(
        enabled=True,
        base_url="https://openrouter.ai/api/v1",
        api_key="openrouter-key",
        prefixes=(SidecarPrefix(prefix="deepseek/", strip=False),),
        connect_timeout_seconds=8.0,
        request_timeout_seconds=600.0,
        models_cache_ttl_seconds=60.0,
        full_models=(),
    )
    client = _ScriptedSidecar(config, "deepseek/deepseek-chat")

    async def load_config():
        return config

    monkeypatch.setattr("app.modules.proxy.api.load_openrouter_sidecar_config", load_config)
    monkeypatch.setattr("app.modules.proxy.api.OpenRouterSidecarClient", lambda _config: client)
    return client


def _install_orcarouter(monkeypatch: pytest.MonkeyPatch) -> _ScriptedSidecar:
    monkeypatch.setenv("CODEX_LB_ORCAROUTER_SIDECAR_ENABLED", "true")
    config = OrcaRouterSidecarConfig(
        enabled=True,
        base_url="https://api.orcarouter.ai/v1",
        api_key="orcarouter-key",
        prefixes=(SidecarPrefix(prefix="orcarouter/", strip=False),),
        connect_timeout_seconds=8.0,
        request_timeout_seconds=600.0,
        models_cache_ttl_seconds=60.0,
        full_models=(),
    )
    client = _ScriptedSidecar(config, "orcarouter/auto")

    async def load_config():
        return config

    monkeypatch.setattr("app.modules.proxy.api.load_orcarouter_sidecar_config", load_config)
    monkeypatch.setattr("app.modules.proxy.api.OrcaRouterSidecarClient", lambda _config: client)
    monkeypatch.setattr("app.modules.proxy.api.get_orcarouter_sidecar_client", lambda _config: client)
    return client


_OPENAI_COMPAT_ENDPOINT_ID = "2c9b8f3a-1e4d-4b7a-9c11-7a0e4d2b1c0a"


def _install_openai_compat(monkeypatch: pytest.MonkeyPatch) -> _ScriptedSidecar:
    config = OpenAICompatSidecarConfig(
        endpoint_id=_OPENAI_COMPAT_ENDPOINT_ID,
        name="Local vLLM",
        enabled=True,
        base_url="http://127.0.0.1:8000/v1",
        api_key=None,
        prefixes=(SidecarPrefix(prefix="vllm/", strip=True),),
        connect_timeout_seconds=8.0,
        request_timeout_seconds=600.0,
        models_cache_ttl_seconds=60.0,
        full_models=(),
    )
    client = _ScriptedSidecar(config, "Qwen/Qwen2.5-7B")

    async def load_configs():
        return (config,)

    monkeypatch.setattr("app.modules.proxy.api.load_openai_compat_configs", load_configs)
    monkeypatch.setattr("app.modules.proxy.api.OpenAICompatSidecarClient", lambda _config: client)
    monkeypatch.setattr("app.modules.proxy.api.get_openai_compat_sidecar_client", lambda _config: client)
    return client


_PROVIDERS = (
    _Provider(
        name="openrouter",
        model="deepseek/deepseek-chat",
        source="openrouter_sidecar",
        settings={
            "openrouterSidecarEnabled": True,
            "openrouterSidecarApiKey": "openrouter-key",
            "openrouterSidecarModelPrefixes": ["deepseek/"],
        },
        install=_install_openrouter,
    ),
    _Provider(
        name="orcarouter",
        model="orcarouter/auto",
        source="orcarouter_sidecar",
        settings={
            "orcarouterSidecarEnabled": True,
            "orcarouterSidecarApiKey": "orcarouter-key",
            "orcarouterSidecarModelPrefixes": ["orcarouter/"],
        },
        install=_install_orcarouter,
    ),
    _Provider(
        name="openai_compat",
        model="vllm/Qwen/Qwen2.5-7B",
        source=f"openai_compat:{_OPENAI_COMPAT_ENDPOINT_ID}",
        settings={},
        install=_install_openai_compat,
    ),
)


_USAGE = {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18}


def _event(data: str, line_ending: str) -> bytes:
    """One SSE event, a ``data`` line per line of ``data``."""

    lines = "".join(f"data: {line}{line_ending}" for line in data.split("\n"))
    return f"{lines}{line_ending}".encode()


def _chunk(*, content: str | None = None, usage: dict[str, int] | None = None, indent: int | None = None) -> str:
    choices = [] if content is None else [{"delta": {"content": content}}]
    body: dict[str, object] = {"id": "c1", "object": "chat.completion.chunk", "choices": choices}
    if usage is not None:
        body["usage"] = usage
    return json.dumps(body, ensure_ascii=False, indent=indent)


def _events(line_ending: str) -> list[bytes]:
    """A content event, a comment-only event, the usage event, and ``[DONE]``."""

    return [
        _event(_chunk(content=NON_ASCII), line_ending),
        f": keep-alive{line_ending}{line_ending}".encode() + _event(_chunk(usage=_USAGE), line_ending),
        _event("[DONE]", line_ending),
    ]


def _multi_line_usage_events(line_ending: str) -> list[bytes]:
    """The usage event's JSON spread over several ``data`` lines, which join back with LF."""

    return [
        _event(_chunk(content=NON_ASCII), line_ending),
        _event(_chunk(usage=_USAGE, indent=1), line_ending),
        _event("[DONE]", line_ending),
    ]


def _usage_on_text_with_unicode_line_separators() -> list[bytes]:
    """Usage riding on the last content event, whose text holds U+2028, U+2029, and U+0085."""

    return [
        _event(_chunk(content="one\u2028two\u2029three\x85four", usage=_USAGE), "\n"),
        _event("[DONE]", "\n"),
    ]


def _split_inside_every_multibyte_character(chunks: list[bytes]) -> list[bytes]:
    """Re-chunk the stream so a chunk boundary falls inside each non-ASCII character."""

    stream = b"".join(chunks)
    cuts = sorted(
        {index + 1 for index, byte in enumerate(stream) if byte >= 0xC0 and index + 1 < len(stream)} | {len(stream)}
    )
    pieces: list[bytes] = []
    start = 0
    for cut in cuts:
        pieces.append(stream[start:cut])
        start = cut
    return pieces


_FRAMINGS: dict[str, Callable[[], list[bytes]]] = {
    "lf": lambda: _events("\n"),
    "crlf": lambda: _events("\r\n"),
    "cr": lambda: _events("\r"),
    "crlf-one-chunk": lambda: [b"".join(_events("\r\n"))],
    "split-multibyte": lambda: _split_inside_every_multibyte_character(_events("\n")),
    "crlf-split-multibyte": lambda: _split_inside_every_multibyte_character(_events("\r\n")),
    "crlf-multi-line-data": lambda: _multi_line_usage_events("\r\n"),
    "crlf-multi-line-data-one-chunk": lambda: [b"".join(_multi_line_usage_events("\r\n"))],
    "unicode-line-separators": _usage_on_text_with_unicode_line_separators,
}


async def _sidecar_log(source: str) -> RequestLog:
    async with SessionLocal() as session:
        logs = list((await session.execute(select(RequestLog).where(RequestLog.source == source))).scalars())
    assert len(logs) == 1, [(log.source, log.status, log.error_code) for log in logs]
    return logs[0]


@pytest.mark.asyncio
@pytest.mark.parametrize("framing", sorted(_FRAMINGS))
@pytest.mark.parametrize("provider", _PROVIDERS, ids=lambda provider: provider.name)
async def test_stream_accounting_survives_real_world_sse_framing(
    async_client, monkeypatch, provider: _Provider, framing: str
) -> None:
    client = provider.install(monkeypatch)
    get_settings.cache_clear()
    try:
        if provider.settings:
            response = await async_client.put("/api/settings", json=provider.settings)
            assert response.status_code == 200, response.text
        client.chunks = _FRAMINGS[framing]()

        async with async_client.stream(
            "POST",
            "/v1/chat/completions",
            json={"model": provider.model, "messages": [{"role": "user", "content": "hi"}], "stream": True},
        ) as streamed:
            body = await streamed.aread()

        assert streamed.status_code == 200
        # The relay is byte-exact whatever the framing.
        assert body.startswith(b"".join(client.chunks))
        log = await _sidecar_log(provider.source)
        assert (log.status, log.error_code) == ("success", None)
        assert (log.input_tokens, log.output_tokens) == (_USAGE["prompt_tokens"], _USAGE["completion_tokens"])
    finally:
        get_settings.cache_clear()
