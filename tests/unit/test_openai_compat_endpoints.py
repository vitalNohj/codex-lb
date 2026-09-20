from __future__ import annotations

import re
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


class TestBaseUrlValidation:
    """A configured base URL decides where the operator's bearer token is sent.

    Reported on https://github.com/vitalNohj/codex-lb/pull/59: the previous
    validator accepted any ``http(s)`` URL with a host, so userinfo, a query, a
    fragment or dot segments all survived into the URL the credential rides on.
    The host itself is deliberately unpinned - the whole point of this feature is
    arbitrary OpenAI-compatible servers - so only the shape is checked.
    """

    @pytest.mark.parametrize(
        ("base_url", "reason"),
        [
            pytest.param(
                "https://attacker@openai.vast.ai/v1",
                "userinfo",
                id="userinfo",
            ),
            pytest.param(
                "https://user:pass@openai.vast.ai/v1",
                "userinfo",
                id="userinfo-with-password",
            ),
            pytest.param(
                "https://openai.vast.ai/v1?redirect=https://attacker.example",
                "query string",
                id="query",
            ),
            pytest.param(
                "https://openai.vast.ai/v1#/../../admin",
                "fragment",
                id="fragment",
            ),
            pytest.param(
                "https://openai.vast.ai/v1/../../admin",
                "'.' or '..' segments",
                id="dot-dot-segments",
            ),
            pytest.param(
                "https://openai.vast.ai/v1/./models",
                "'.' or '..' segments",
                id="single-dot-segment",
            ),
            # Percent-encoded dot segments are the bypass a literal-only check
            # misses: the HTTP client canonicalizes AFTER validation, so
            # ``/v1/%2e%2e/%2e%2e/admin`` + ``/models`` leaves as
            # ``/admin/models``. Verified against yarl, the URL type aiohttp uses.
            pytest.param(
                "https://openai.vast.ai/v1/%2e%2e/%2e%2e/admin",
                "percent-encoded characters",
                id="encoded-dot-dot-segments",
            ),
            pytest.param(
                "https://openai.vast.ai/v1/..%2Fadmin",
                "percent-encoded characters",
                id="encoded-slash",
            ),
            pytest.param(
                "https://openai.vast.ai/v1/%2E%2E/admin",
                "percent-encoded characters",
                id="encoded-dot-dot-uppercase",
            ),
            pytest.param(
                "https://openai.vast.ai/v1\\..\\admin",
                "backslashes",
                id="backslash-path-traversal",
            ),
            pytest.param("ftp://openai.vast.ai/v1", "http(s) URL", id="non-http-scheme"),
            pytest.param("file:///etc/passwd", "http(s) URL", id="file-scheme"),
            pytest.param("https:///v1", "must contain a host", id="no-host"),
            pytest.param("   ", "must not be blank", id="blank"),
        ],
    )
    def test_a_credential_bearing_url_shape_is_refused_at_save_time(self, base_url: str, reason: str) -> None:
        encryptor = TokenEncryptor()

        with pytest.raises(ValueError, match=re.escape(reason)):
            merge_openai_compat_endpoints("[]", [_update(base_url=base_url)], encryptor)

    @pytest.mark.parametrize(
        ("base_url", "expected"),
        [
            pytest.param(
                "https://openai.vast.ai/demo/v1/",
                "https://openai.vast.ai/demo/v1",
                id="trailing-slash-stripped",
            ),
            pytest.param(
                "HTTPS://OpenAI.Vast.AI/demo/v1",
                "https://openai.vast.ai/demo/v1",
                # Scheme and host are case-insensitive per RFC 3986, so two
                # spellings of one endpoint must not read as two endpoints.
                id="scheme-and-host-lowercased",
            ),
            pytest.param("http://localhost:11434/v1", "http://localhost:11434/v1", id="plain-http-with-port"),
            pytest.param("https://openai.vast.ai", "https://openai.vast.ai", id="bare-host-no-path"),
            pytest.param("http://[::1]:8000/v1", "http://[::1]:8000/v1", id="ipv6-literal"),
        ],
    )
    def test_a_legitimate_arbitrary_host_is_accepted_and_canonicalized(self, base_url: str, expected: str) -> None:
        """Arbitrary hosts stay allowed: only the shape is validated, never the host."""

        encryptor = TokenEncryptor()

        merged = merge_openai_compat_endpoints("[]", [_update(base_url=base_url)], encryptor)

        assert merged[0].base_url == expected

    def test_a_stored_blob_with_a_refused_url_is_dropped_rather_than_loaded(self) -> None:
        """A blob written before this check (or edited out of band) must not route.

        ``_parse_stored_entry`` runs the same validator, so a persisted endpoint
        whose URL would be refused today never becomes a routable config.
        """

        raw = (
            '[{"id":"' + ENDPOINT_ID + '","name":"Vast",'
            '"base_url":"https://attacker@openai.vast.ai/v1","enabled":true}]'
        )

        assert parse_openai_compat_endpoints(raw) == ()


def test_percent_encoded_traversal_cannot_survive_client_canonicalization() -> None:
    """The bypass, demonstrated against the URL type aiohttp actually uses.

    A literal-only dot-segment check reads as a defence while letting the exact
    same redirection through, which is worse than no check: the request library
    canonicalizes the URL after validation. This asserts the wire target that
    WOULD have resulted, so the test documents the consequence rather than just
    the rejection.
    """

    import yarl

    hostile = "https://openai.vast.ai/v1/%2e%2e/%2e%2e/admin"
    # What the credential-bearing request would have become had this been accepted.
    assert str(yarl.URL(hostile + "/models")) == "https://openai.vast.ai/admin/models"

    encryptor = TokenEncryptor()
    with pytest.raises(ValueError, match="percent-encoded"):
        merge_openai_compat_endpoints("[]", [_update(base_url=hostile)], encryptor)


def test_a_stored_blob_with_encoded_traversal_is_dropped_rather_than_loaded() -> None:
    """The client re-validates, so such a blob never becomes a routable config."""

    raw = (
        '[{"id":"' + ENDPOINT_ID + '","name":"Vast",'
        '"base_url":"https://openai.vast.ai/v1/%2e%2e/%2e%2e/admin","enabled":true}]'
    )

    assert parse_openai_compat_endpoints(raw) == ()
