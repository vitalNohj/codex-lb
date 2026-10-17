"""Vision advertised for sidecar rows on ``/v1/models``.

OpenAI-compatible catalogs often omit modality metadata. Those rows are not
image-capable. A row is vision-capable only when its own catalog says so, or
when it is a Claude model whose published context window we already treat as
known — every model in that table accepts image input. Dated and unknown
Claude ids do not borrow another model's modalities.
"""

from __future__ import annotations

from collections.abc import Mapping

from app.core.types import JsonValue
from app.core.utils.json_guards import is_json_mapping
from app.modules.proxy.claude_sidecar_dispatch import claude_sidecar_context_window


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


def sidecar_supports_vision(
    raw: Mapping[str, JsonValue] | None,
    *,
    claude_model: str | None = None,
) -> bool:
    """Whether a sidecar catalog row should advertise image input."""

    modalities = catalog_input_modalities(raw)
    if modalities is not None:
        return "image" in modalities
    if claude_model is not None and claude_sidecar_context_window(claude_model) is not None:
        return True
    return False


def _string_list(value: JsonValue) -> list[str] | None:
    if not isinstance(value, list):
        return None
    return [item.strip().lower() for item in value if isinstance(item, str) and item.strip()]
