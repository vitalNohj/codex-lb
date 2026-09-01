"""A serving context must say which of three different things happened.

The maintenance pass acts on the difference: a switched-off integration is left
untouched and reported as disabled, while an integration that could not be
consulted has its records preserved and is reported as a failure. Collapsing a
settings-read failure into "disabled" tells the operator they turned something off
when in fact the pass could not run.
"""

from __future__ import annotations

import pytest

import app.modules.proxy.external_pricing_sources as pricing_sources
from app.modules.proxy.external_pricing_sources import (
    _load_cliproxy_context,
    _load_openrouter_context,
    _load_orcarouter_context,
)

pytestmark = pytest.mark.unit


_LOADERS = (
    ("orcarouter", _load_orcarouter_context, "app.modules.proxy.orcarouter_sidecar_dispatch"),
    ("openrouter", _load_openrouter_context, "app.modules.proxy.openrouter_sidecar_dispatch"),
    ("cliproxy", _load_cliproxy_context, "app.modules.proxy.claude_sidecar_dispatch"),
)

_CONFIG_LOADERS = {
    "orcarouter": "load_orcarouter_sidecar_config",
    "openrouter": "load_openrouter_sidecar_config",
    "cliproxy": "load_sidecar_config",
}


def _patch_config(monkeypatch, module: str, provider: str, result):
    import importlib

    async def _load():
        return result

    monkeypatch.setattr(importlib.import_module(module), _CONFIG_LOADERS[provider], _load)


@pytest.mark.parametrize(("provider", "loader", "module"), _LOADERS)
@pytest.mark.asyncio
async def test_a_settings_read_failure_is_not_reported_as_a_disabled_integration(
    monkeypatch,
    provider: str,
    loader,
    module: str,
) -> None:
    """``None`` from the config loader means the settings could not be read.

    Treating it as ``disabled`` made ``codex-lb model-prices refresh`` print
    "Skipped, integration disabled: N" with no failure line during a transient
    settings/DB blip, so the operator concluded they had switched it off.
    """

    _patch_config(monkeypatch, module, provider, None)

    context = await loader(provider)

    assert context is None, "an unconsultable integration must read as a failure, not a switch-off"


@pytest.mark.parametrize(("provider", "loader", "module"), _LOADERS)
@pytest.mark.asyncio
async def test_a_switched_off_integration_reports_itself_as_disabled(
    monkeypatch,
    provider: str,
    loader,
    module: str,
) -> None:
    class _Prefix:
        prefix = "routed/"
        strip = True

    class _DisabledConfig:
        enabled = False
        prefixes = (_Prefix(),)

    async def _aliases():
        return {"local-model": "vendor/canonical-model"}

    _patch_config(monkeypatch, module, provider, _DisabledConfig())
    monkeypatch.setattr(pricing_sources, "load_model_aliases", _aliases)

    context = await loader(provider)

    assert context is not None
    assert context.integration_enabled is False
    assert context.serving_catalog_missing is False, "a disabled integration has not failed to answer"
    assert context.aliases == {"local-model": "vendor/canonical-model"}
    assert context.prefixes == (("routed/", True),)
