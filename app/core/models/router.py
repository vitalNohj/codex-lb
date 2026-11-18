"""CLIProxyAPI model metadata, with a bundled and last-good offline snapshot."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Annotated

import aiohttp
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from app.core.metadata_store import write_metadata
from app.core.types import JsonValue

logger = logging.getLogger(__name__)
ROUTER_MODELS_URL = "https://raw.githubusercontent.com/router-for-me/models/main/models.json"
SNAPSHOT_PATH = Path(__file__).with_name("cliproxy_snapshot.json")
MAX_CATALOG_BYTES = 4 * 1024 * 1024
PositiveInt = Annotated[int, Field(strict=True, gt=0)]


class Thinking(BaseModel):
    model_config = ConfigDict(extra="ignore")
    levels: tuple[str, ...] | None = None
    min: int | None = None
    max: int | None = None
    zero_allowed: bool | None = None
    dynamic_allowed: bool | None = None


class RouterModel(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)
    id: str = Field(min_length=1)
    owned_by: str | None = None
    catalog_provider: str | None = None
    context_length: PositiveInt | None = None
    max_completion_tokens: PositiveInt | None = None
    thinking: Thinking | None = None
    input_modalities: tuple[str, ...] | None = Field(default=None, alias="supportedInputModalities")
    output_modalities: tuple[str, ...] | None = Field(default=None, alias="supportedOutputModalities")


_ADAPTER = TypeAdapter(dict[str, list[RouterModel]])
_models: dict[str, RouterModel] | None = None


def parse_router_models(payload: JsonValue) -> dict[str, RouterModel]:
    groups = _ADAPTER.validate_python(payload)
    result: dict[str, RouterModel] = {}
    provider_groups = {"claude": "anthropic", "codex": "openai", "gemini": "google", "grok": "xai"}
    for group, entries in groups.items():
        for entry in entries:
            entry = entry.model_copy(update={"catalog_provider": provider_groups.get(group, entry.owned_by or group)})
            # Native provider groups precede cross-provider mirrors in this
            # source. Later duplicate plan listings must not lower a ceiling.
            result.setdefault(entry.id.strip().lower(), entry)
    if not result:
        raise ValueError("CLIProxyAPI catalog supplied no models")
    return result


def get_router_models() -> dict[str, RouterModel]:
    global _models
    if _models is None:
        _models = parse_router_models(json.loads(SNAPSHOT_PATH.read_text()))
    return _models


def restore_router_models(path: Path) -> None:
    global _models
    try:
        _models = parse_router_models(json.loads(path.read_text()))
    except (OSError, ValueError):
        get_router_models()


async def refresh_router_models(path: Path) -> None:
    """Publish only a complete validated response; failure retains last-good data."""
    global _models
    async with aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=20),
        trust_env=True,
        headers={"User-Agent": "codex-lb", "Accept": "application/json"},
    ) as session:
        async with session.get(ROUTER_MODELS_URL) as response:
            response.raise_for_status()
            body = bytearray()
            async for chunk in response.content.iter_chunked(64 * 1024):
                body.extend(chunk)
                if len(body) > MAX_CATALOG_BYTES:
                    raise ValueError("CLIProxyAPI model response too large")
    models = parse_router_models(json.loads(body))
    # Persistence failure must not discard a valid live response.
    _models = models
    await asyncio.to_thread(write_metadata, path, body.decode("utf-8"))
    logger.info("Refreshed CLIProxyAPI model metadata: models=%d", len(models))
