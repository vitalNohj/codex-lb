"""Input modalities advertised for sidecar rows on ``/v1/models``.

Claude rows use the exact public catalog entry when available. Provider-row
metadata and the legacy fixed-model vision set remain the offline fallback.
Limits alone never imply image support.
"""

from __future__ import annotations

from collections.abc import Mapping

from app.core.models.catalog import catalog_input_modalities as _catalog_input_modalities
from app.core.models.catalog import resolve_model
from app.core.types import JsonValue


def catalog_input_modalities(raw: Mapping[str, JsonValue] | None) -> list[str] | None:
    modalities = _catalog_input_modalities(raw)
    return list(modalities) if modalities is not None else None


def sidecar_input_modalities(
    raw: Mapping[str, JsonValue] | None,
    *,
    claude_model: str | None = None,
) -> list[str]:
    """Resolve one row's modalities without inferring them from its limits."""
    modalities = catalog_input_modalities(raw)
    if claude_model is not None:
        catalog_raw: dict[str, JsonValue] | None = None
        if modalities is not None:
            catalog_raw = {"input_modalities": list(modalities)}
        record = resolve_model(claude_model, raw=catalog_raw)
        if record.input_modalities is not None:
            return list(record.input_modalities)
    if modalities is not None:
        return ["text", "image"] if "image" in modalities else ["text"]
    return ["text"]


def sidecar_supports_vision(
    raw: Mapping[str, JsonValue] | None,
    *,
    claude_model: str | None = None,
) -> bool:
    """Whether a sidecar catalog row should advertise image input."""
    return "image" in sidecar_input_modalities(raw, claude_model=claude_model)
