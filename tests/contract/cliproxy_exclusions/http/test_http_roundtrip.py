"""Opt-in cross-language contract against a real CLIProxyAPI HTTP handler."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

_ALPHA = "alpha.json"
_BRAVO = "bravo.json"
_PATTERN = "claude-opus-4-*"
_TOKEN_FIELDS = {"access_token", "refresh_token", "token", "id_token"}


def _accounts(body: dict) -> dict[str, dict]:
    return {entry["name"]: entry for entry in body["accounts"]}


def _assert_token_private(value: object) -> None:
    if isinstance(value, dict):
        assert not (_TOKEN_FIELDS & value.keys())
        for child in value.values():
            _assert_token_private(child)
    elif isinstance(value, list):
        for child in value:
            _assert_token_private(child)


@pytest.mark.asyncio
async def test_real_cliproxy_handler_save_readback_clear_without_app_lifespan(monkeypatch) -> None:
    # Imports occur only after the runner has installed the private environment,
    # disabled unrelated feature starts, and selected the private database.
    from app.core.clients.http import close_http_client, init_http_client
    from app.core.config.settings import get_settings
    from app.db.models import Base
    from app.db.session import close_db, engine
    from app.main import create_app

    base_url = os.environ["CODEX_LB_HTTP_FIXTURE_BASE_URL"]
    auth_dir = Path(os.environ["CODEX_LB_HTTP_FIXTURE_AUTH_DIR"])
    monkeypatch.setattr(
        "app.modules.claude_sidecar.excluded_models.default_auth_dir",
        lambda: auth_dir,
    )

    get_settings.cache_clear()
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    await init_http_client()
    try:
        # Lifespan is intentionally not entered. This drives only the real API
        # route, request-scoped settings/service code and sidecar HTTP client.
        app = create_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            configured = await client.put(
                "/api/settings",
                json={
                    "claudeSidecarEnabled": True,
                    "claudeSidecarBaseUrl": base_url,
                    "claudeSidecarApiKey": "synthetic-client-key",
                    "claudeSidecarManagementKey": "synthetic-management-key",
                },
            )
            assert configured.status_code == 200, configured.text

            saved = await client.put(
                "/api/claude-sidecar/routing/excluded-models",
                json={"name": _ALPHA, "excludedModels": [_PATTERN]},
            )
            assert saved.status_code == 200, saved.text
            saved_body = saved.json()
            assert saved_body["status"] == "healthy"
            assert saved_body["savedAccount"]["excludedModels"] == [_PATTERN]
            _assert_token_private(saved_body)

            readback = await client.get("/api/claude-sidecar/routing")
            assert readback.status_code == 200, readback.text
            read_body = readback.json()
            accounts = _accounts(read_body)
            assert accounts[_ALPHA]["excludedModels"] == [_PATTERN]
            assert accounts[_ALPHA]["excludedModelsState"] == "available"
            assert accounts[_BRAVO]["excludedModels"] == []
            assert accounts[_BRAVO]["excludedModelsState"] == "available"
            _assert_token_private(read_body)

            alpha_disk = json.loads((auth_dir / _ALPHA).read_text(encoding="utf-8"))
            bravo_disk = json.loads((auth_dir / _BRAVO).read_text(encoding="utf-8"))
            assert alpha_disk["excluded_models"] == [_PATTERN]
            assert "excluded_models" not in bravo_disk

            cleared = await client.put(
                "/api/claude-sidecar/routing/excluded-models",
                json={"name": _ALPHA, "excludedModels": []},
            )
            assert cleared.status_code == 200, cleared.text
            cleared_body = cleared.json()
            assert cleared_body["status"] == "healthy"
            assert cleared_body["savedAccount"]["excludedModels"] == []
            _assert_token_private(cleared_body)

            final_read = await client.get("/api/claude-sidecar/routing")
            assert final_read.status_code == 200, final_read.text
            final_body = final_read.json()
            final_accounts = _accounts(final_body)
            assert final_accounts[_ALPHA]["excludedModels"] == []
            assert final_accounts[_ALPHA]["excludedModelsState"] == "available"
            assert final_accounts[_BRAVO]["excludedModels"] == []
            assert final_accounts[_BRAVO]["excludedModelsState"] == "available"
            _assert_token_private(final_body)

            assert json.loads((auth_dir / _ALPHA).read_text(encoding="utf-8"))["excluded_models"] == []
            assert "excluded_models" not in json.loads((auth_dir / _BRAVO).read_text(encoding="utf-8"))
    finally:
        await close_http_client()
        await close_db()
