from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.usage import pricing_catalog as catalog
from app.core.usage.model_capabilities import (
    ModelCapabilities,
    decode_model_capabilities,
    merge_model_capabilities,
    parse_models_dev_capabilities,
)

pytestmark = pytest.mark.unit


@pytest.fixture
def payload():
    return json.loads((Path(__file__).parents[1] / "fixtures" / "claude_models_dev.json").read_text())


@pytest.fixture(autouse=True)
def isolated_capabilities(monkeypatch):
    monkeypatch.setattr(catalog, "_capabilities", {})


def test_models_dev_capabilities_are_separate_from_accounting_prices(payload):
    capabilities = parse_models_dev_capabilities(payload)
    assert capabilities == {"claude-fable-5-2": ModelCapabilities(("text", "image", "pdf"), 1_000_000, 128_000)}
    with pytest.raises(ValueError, match="no valid OpenAI prices"):
        catalog.parse_models_dev(payload)


@pytest.mark.parametrize("prefix", ["", "cc/", "cp-", "cp_"])
def test_capability_lookup_removes_one_routing_prefix_only(payload, prefix):
    catalog.install_model_capabilities(parse_models_dev_capabilities(payload))
    assert catalog.get_model_capabilities(prefix + "claude-fable-5-2") == ModelCapabilities(
        ("text", "image", "pdf"), 1_000_000, 128_000
    )
    for model in (
        "claude-fable-5.2",
        "claude-fable-5-2-20261109",
        "claude-fable-5-2-thinking-max",
        "claude-fable-5-20",
        "cc/claude-fable-5-2",
        "unknown",
    ):
        assert catalog.get_model_capabilities("cc/" + model) is None


def test_dotted_dated_and_effort_rows_can_have_their_own_exact_metadata(payload):
    entry = payload["anthropic"]["models"].pop("claude-fable-5-2")
    models = ["claude-fable-5.2", "claude-fable-5-2-20261109", "claude-fable-5-2-thinking-max"]
    payload["anthropic"]["models"] = {model: entry for model in models}
    catalog.install_model_capabilities(parse_models_dev_capabilities(payload))
    for model in models:
        assert catalog.get_model_capabilities("cc/" + model) is not None
    assert catalog.get_model_capabilities("claude-fable-5-2") is None


@pytest.mark.parametrize("bad", [None, True, False, 0, -1, 128_000.0, "128000", float("inf"), {}, []])
def test_invalid_limits_do_not_replace_valid_fields(payload, bad):
    previous = parse_models_dev_capabilities(payload)
    payload["anthropic"]["models"]["claude-fable-5-2"]["limit"] = {"context": bad, "output": bad}
    parsed = parse_models_dev_capabilities(payload)
    assert parsed["claude-fable-5-2"] == ModelCapabilities(("text", "image", "pdf"))
    assert merge_model_capabilities(parsed, previous) == previous


@pytest.mark.parametrize("bad", [None, "text,image", {}, [True], ["text", 1], [""]])
def test_invalid_modalities_do_not_replace_last_good_metadata(payload, bad):
    previous = parse_models_dev_capabilities(payload)
    payload["anthropic"]["models"]["claude-fable-5-2"]["modalities"]["input"] = bad
    parsed = parse_models_dev_capabilities(payload)
    assert parsed["claude-fable-5-2"].input_modalities is None
    assert merge_model_capabilities(parsed, previous) == previous


def test_snapshot_round_trip_partial_updates_and_legacy_fallback(payload, tmp_path, monkeypatch):
    legacy = json.loads(catalog.encode_snapshot(catalog.get_active_prices()))
    legacy.pop("model_capabilities")
    bundle = tmp_path / "legacy-pricing.json"
    bundle.write_text(json.dumps(legacy))
    monkeypatch.setattr(catalog, "BUNDLE_PATH", bundle)
    monkeypatch.setattr(catalog, "_capabilities", None)
    assert decode_model_capabilities(legacy) == {}
    assert catalog.get_model_capabilities("claude-fable-5-2") is None
    original = parse_models_dev_capabilities(payload)
    encoded = catalog.encode_snapshot(catalog.get_active_prices(), capabilities=original)
    assert decode_model_capabilities(json.loads(encoded)) == original
    catalog.install_model_capabilities(original)
    catalog.install_model_capabilities({"claude-next": ModelCapabilities(context_window=200_000)})
    assert catalog.get_model_capabilities("claude-fable-5-2") == original["claude-fable-5-2"]
    catalog.install_model_capabilities({"claude-fable-5-2": ModelCapabilities(("text",))})
    assert catalog.get_model_capabilities("claude-fable-5-2") == ModelCapabilities(("text",), 1_000_000, 128_000)


@pytest.mark.parametrize("payload", [None, [], {}, {"anthropic": []}, {"anthropic": {"models": []}}])
def test_missing_or_malformed_capability_catalog_is_empty(payload):
    assert parse_models_dev_capabilities(payload) == {}
    assert decode_model_capabilities(payload) == {}
