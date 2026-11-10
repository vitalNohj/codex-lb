"""Input modalities advertised for sidecar rows on ``/v1/models``.

Claude rows use the exact public catalog entry when available. Provider-row
metadata and the legacy fixed-model vision set remain the offline fallback.
Limits alone never imply image support.
"""

from __future__ import annotations

from collections.abc import Mapping

from app.core.types import JsonValue
from app.core.usage.pricing_catalog import get_model_capabilities
from app.core.utils.json_guards import is_json_mapping
from app.modules.proxy.claude_sidecar_dispatch import has_fixed_claude_sidecar_bounds


def catalog_input_modalities(raw: Mapping[str, JsonValue] | None) -> list[str] | None:
    """Modalities a provider catalog entry actually declares, or ``None``.

    ``None`` means the entry said nothing. An empty list means it declared
    modalities and none of them are usable strings.
    """

    if raw is None:
        return None
    direct = _string_list(raw.get("input_modalities"))
    if direct is not None:
        return direct
    architecture = raw.get("architecture")
    if not is_json_mapping(architecture):
        return None
    nested = _string_list(architecture.get("input_modalities"))
    if nested is not None:
        return nested
    modality = architecture.get("modality")
    if not isinstance(modality, str) or "->" not in modality:
        return None
    left = modality.split("->", 1)[0]
    parts = [part.strip().lower() for part in left.split("+") if part.strip()]
    return parts or None


def sidecar_input_modalities(
    raw: Mapping[str, JsonValue] | None,
    *,
    claude_model: str | None = None,
) -> list[str]:
    """Resolve one row's modalities without inferring them from its limits."""
    if claude_model is not None:
        metadata = get_model_capabilities(claude_model)
        if metadata is not None and metadata.input_modalities is not None:
            return list(metadata.input_modalities)
    modalities = catalog_input_modalities(raw)
    if modalities is not None:
        # Preserve the existing provider-row advertisement when no public
        # Claude modalities are available, including text-only for an empty list.
        return ["text", "image"] if "image" in modalities else ["text"]
    if claude_model is not None and has_fixed_claude_sidecar_bounds(claude_model):
        return ["text", "image"]
    return ["text"]


def sidecar_supports_vision(
    raw: Mapping[str, JsonValue] | None,
    *,
    claude_model: str | None = None,
) -> bool:
    """Whether a sidecar catalog row should advertise image input."""
    return "image" in sidecar_input_modalities(raw, claude_model=claude_model)


def _string_list(value: JsonValue) -> list[str] | None:
    if not isinstance(value, list):
        return None
    return [item.strip().lower() for item in value if isinstance(item, str) and item.strip()]
