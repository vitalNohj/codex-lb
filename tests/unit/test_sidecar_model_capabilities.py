from __future__ import annotations

import pytest

from app.modules.proxy.sidecar_model_capabilities import (
    catalog_input_modalities,
    sidecar_supports_vision,
)

pytestmark = pytest.mark.unit


def test_catalog_input_modalities_reads_direct_and_architecture_fields() -> None:
    assert catalog_input_modalities(None) is None
    assert catalog_input_modalities({}) is None
    assert catalog_input_modalities({"input_modalities": ["Text", " Image "]}) == ["text", "image"]
    assert catalog_input_modalities({"architecture": {"input_modalities": ["text"]}}) == ["text"]
    assert catalog_input_modalities({"architecture": {"modality": "text+image->text"}}) == ["text", "image"]
    direct_wins = catalog_input_modalities(
        {"input_modalities": ["text"], "architecture": {"modality": "text+image->text"}}
    )
    assert direct_wins == ["text"]
    assert catalog_input_modalities({"input_modalities": []}) == []


def test_sidecar_supports_vision_uses_declared_modalities_before_claude() -> None:
    assert sidecar_supports_vision(None) is False
    assert sidecar_supports_vision({"input_modalities": ["text", "image"]}) is True
    assert sidecar_supports_vision({"input_modalities": ["text"]}, claude_model="claude-opus-4-7") is False
    assert sidecar_supports_vision(None, claude_model="claude-opus-4-7") is True
    assert sidecar_supports_vision(None, claude_model="claude-sonnet-4-5-20250929") is False
    assert sidecar_supports_vision(None, claude_model="claude-unreleased-9") is False
