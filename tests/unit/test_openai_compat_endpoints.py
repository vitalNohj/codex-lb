from __future__ import annotations

from datetime import datetime

import pytest

from app.core.clients.claude_sidecar import SidecarPrefix
from app.core.crypto import TokenEncryptor
from app.modules.openai_compat.endpoints import (
    OPENAI_COMPAT_MAX_ENDPOINTS,
    OpenAICompatEndpointUpdateData,
    StoredOpenAICompatEndpoint,
    decrypt_endpoint_api_key,
    dump_openai_compat_endpoints,
    merge_openai_compat_endpoints,
    parse_openai_compat_endpoints,
    patch_endpoint_health,
)

pytestmark = pytest.mark.unit

ENDPOINT_ID = "2c9b8f3a-1e4d-4b7a-9c11-7a0e4d2b1c0a"


def _update(**overrides) -> OpenAICompatEndpointUpdateData:
    values = {
        "id": ENDPOINT_ID,
        "name": "Vast",
        "enabled": True,
        "base_url": "https://openai.vast.ai/demo/v1/",
        "api_key": None,
        "clear_api_key": False,
        "prefixes": [SidecarPrefix(prefix="vast/", strip=True)],
        "full_models": ["Qwen/Qwen2.5-7B"],
        "connect_timeout_seconds": 8.0,
        "request_timeout_seconds": 600.0,
        "models_cache_ttl_seconds": 60.0,
        "default_reasoning_effort": None,
    }
    values.update(overrides)
    return OpenAICompatEndpointUpdateData(**values)


def _stored(**overrides) -> StoredOpenAICompatEndpoint:
    values = {
        "id": ENDPOINT_ID,
        "name": "Vast",
        "enabled": True,
        "base_url": "https://openai.vast.ai/demo/v1",
        "api_key_encrypted_b64": None,
        "prefixes": (SidecarPrefix(prefix="vast/", strip=True),),
        "full_models": ("Qwen/Qwen2.5-7B",),
        "connect_timeout_seconds": 8.0,
        "request_timeout_seconds": 600.0,
        "models_cache_ttl_seconds": 60.0,
        "default_reasoning_effort": None,
        "last_health_status": "healthy",
        "last_health_message": "Vast reachable",
        "last_checked_at": datetime(2026, 9, 19, 12, 0, 0),
        "last_model_count": 1,
    }
    values.update(overrides)
    return StoredOpenAICompatEndpoint(**values)


def test_parse_dump_round_trip_preserves_operator_fields() -> None:
    dumped = dump_openai_compat_endpoints((_stored(),))
    parsed = parse_openai_compat_endpoints(dumped)

    assert len(parsed) == 1
    endpoint = parsed[0]
    assert endpoint.id == ENDPOINT_ID
    assert endpoint.name == "Vast"
    assert endpoint.base_url == "https://openai.vast.ai/demo/v1"
    assert endpoint.provider_id == f"openai_compat:{ENDPOINT_ID}"
    assert endpoint.account_id == f"openai-compat-{ENDPOINT_ID}"
    assert endpoint.last_health_status == "healthy"
    assert endpoint.last_model_count == 1


def test_parse_skips_invalid_entries_and_blank_blobs() -> None:
    assert parse_openai_compat_endpoints(None) == ()
    assert parse_openai_compat_endpoints("not-json") == ()
    assert parse_openai_compat_endpoints("{}") == ()
    assert parse_openai_compat_endpoints('[{"id":"nope","name":"Vast","base_url":"https://x.example/v1"}]') == ()


def test_merge_encrypts_api_key_and_omits_plaintext_from_json() -> None:
    encryptor = TokenEncryptor()
    merged = merge_openai_compat_endpoints("[]", [_update(api_key="vast-secret")], encryptor)

    assert len(merged) == 1
    assert merged[0].api_key_configured is True
    assert decrypt_endpoint_api_key(merged[0], encryptor) == "vast-secret"
    dumped = dump_openai_compat_endpoints(merged)
    assert "vast-secret" not in dumped
    assert merged[0].base_url == "https://openai.vast.ai/demo/v1"


def test_merge_preserves_health_and_existing_key_when_operator_omits_them() -> None:
    encryptor = TokenEncryptor()
    current = dump_openai_compat_endpoints((_stored(api_key_encrypted_b64="c2VjcmV0"),))
    merged = merge_openai_compat_endpoints(current, [_update(api_key=None)], encryptor)

    assert merged[0].api_key_encrypted_b64 == "c2VjcmV0"
    assert merged[0].last_health_status == "healthy"
    assert merged[0].last_health_message == "Vast reachable"
    assert merged[0].last_model_count == 1


def test_merge_rejects_duplicate_names_and_the_cap() -> None:
    encryptor = TokenEncryptor()
    with pytest.raises(ValueError, match="names must be unique"):
        merge_openai_compat_endpoints(
            "[]",
            [
                _update(),
                _update(id="3d0c9e4b-2f5e-4c8b-8d22-8b1f5e3c2d1b", name="vast"),
            ],
            encryptor,
        )

    over_cap = [
        _update(id=f"00000000-0000-4000-8000-{index:012d}", name=f"EP{index}")
        for index in range(OPENAI_COMPAT_MAX_ENDPOINTS + 1)
    ]
    with pytest.raises(ValueError, match="cannot exceed"):
        merge_openai_compat_endpoints("[]", over_cap, encryptor)


def test_patch_endpoint_health_updates_only_the_named_row() -> None:
    other = _stored(id="3d0c9e4b-2f5e-4c8b-8d22-8b1f5e3c2d1b", name="vLLM", last_health_status=None)
    patched = patch_endpoint_health(
        (_stored(), other),
        ENDPOINT_ID,
        last_health_status="unreachable",
        last_health_message="connection refused",
        last_checked_at=datetime(2026, 9, 19, 13, 0, 0),
        last_model_count=None,
    )

    by_id = {endpoint.id: endpoint for endpoint in patched}
    assert by_id[ENDPOINT_ID].last_health_status == "unreachable"
    assert by_id[other.id].last_health_status is None
