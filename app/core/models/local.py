"""Validated, packaged operator corrections; no network or registry dependency."""

from __future__ import annotations

import json
import math
from dataclasses import asdict
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.models.types import ModelPrice
from app.core.types import JsonValue

LOCAL_PATH = Path(__file__).resolve().parents[3] / "config" / "models.local.json"


class LocalModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    aliases: tuple[str, ...] = ()
    native_aliases: bool = False
    native_suffixes: tuple[str, ...] = ()
    prefer_canonical_price: bool = False
    provider: str | None = None
    capability_providers: tuple[str, ...] = ()
    respect_upstream_ceiling: bool = False
    context_window: int | None = Field(default=None, strict=True, gt=0)
    max_context_window: int | None = Field(default=None, strict=True, gt=0)
    max_output_tokens: int | None = Field(default=None, strict=True, gt=0)
    fallback_max_output_tokens: int | None = Field(default=None, strict=True, gt=0)
    thinking_levels: tuple[str, ...] | None = None
    input_modalities: tuple[str, ...] | None = None
    output_modalities: tuple[str, ...] | None = None
    price: ModelPrice | None = None
    fallback_price: ModelPrice | None = None
    price_overrides: dict[str, float] = Field(default_factory=dict)
    # A rate for one integration must not replace another integration's rate.
    provider_prices: dict[str, ModelPrice] = Field(default_factory=dict)
    legacy_sidecar_bounds: bool = False
    codex: dict[str, JsonValue] | None = None

    @model_validator(mode="after")
    def valid_prices(self) -> LocalModel:
        for key, value in self.price_overrides.items():
            if key not in ModelPrice.__dataclass_fields__ or not math.isfinite(value) or value < 0:
                raise ValueError(f"Invalid price override: {key}")
        for price in [self.price, self.fallback_price, *self.provider_prices.values()]:
            if price is not None and any(
                value is not None and (not math.isfinite(value) or value < 0) for value in asdict(price).values()
            ):
                raise ValueError("Prices must be finite and nonnegative")
        return self


class LocalCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal[1]
    models: dict[str, LocalModel]


@lru_cache(maxsize=1)
def load_local_catalog() -> LocalCatalog:
    return LocalCatalog.model_validate_json(LOCAL_PATH.read_text())


def local_prices() -> dict[str, ModelPrice]:
    return {
        key: price
        for key, entry in load_local_catalog().models.items()
        if (price := entry.price or entry.fallback_price) is not None
    }


def local_aliases() -> dict[str, str]:
    return {alias: key for key, entry in load_local_catalog().models.items() for alias in entry.aliases}


def codex_bootstrap_payloads() -> list[dict[str, JsonValue]]:
    # Round-trip to make mutable compatibility metadata private to the registry.
    return [json.loads(json.dumps(entry.codex)) for entry in load_local_catalog().models.values() if entry.codex]
