"""Stored OpenAI-compatible endpoint list.

One JSON column on ``dashboard_settings`` holds every generic endpoint. This
module is the only parser/serializer for that blob so settings, routing, and
the dashboard API cannot drift.
"""

from __future__ import annotations

import base64
import json
import logging
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from app.core.clients.claude_sidecar import SidecarPrefix
from app.core.clients.openai_compat_sidecar import (
    OpenAICompatBaseUrlError,
    normalize_openai_compat_base_url,
)
from app.core.crypto import TokenEncryptor
from app.modules.proxy.sidecar_routing import parse_sidecar_full_models, parse_sidecar_prefixes

logger = logging.getLogger(__name__)

OPENAI_COMPAT_PROVIDER_PREFIX = "openai_compat:"
OPENAI_COMPAT_ACCOUNT_PREFIX = "openai-compat-"
OPENAI_COMPAT_MAX_ENDPOINTS = 32
OPENAI_COMPAT_PRICING_PROVIDER_PREFIX = OPENAI_COMPAT_PROVIDER_PREFIX

_DEFAULT_CONNECT_TIMEOUT_SECONDS = 8.0
_DEFAULT_REQUEST_TIMEOUT_SECONDS = 600.0
_DEFAULT_MODELS_CACHE_TTL_SECONDS = 60.0


@dataclass(frozen=True, slots=True)
class StoredOpenAICompatEndpoint:
    id: str
    name: str
    enabled: bool
    base_url: str
    api_key_encrypted_b64: str | None
    prefixes: tuple[SidecarPrefix, ...]
    full_models: tuple[str, ...]
    connect_timeout_seconds: float
    request_timeout_seconds: float
    models_cache_ttl_seconds: float
    default_reasoning_effort: str | None
    last_health_status: str | None
    last_health_message: str | None
    last_checked_at: datetime | None
    last_model_count: int | None

    @property
    def provider_id(self) -> str:
        return openai_compat_provider_id(self.id)

    @property
    def account_id(self) -> str:
        return openai_compat_account_id(self.id)

    @property
    def api_key_configured(self) -> bool:
        return bool(self.api_key_encrypted_b64)


@dataclass(frozen=True, slots=True)
class OpenAICompatEndpointUpdateData:
    id: str | None
    name: str
    enabled: bool
    base_url: str
    api_key: str | None
    clear_api_key: bool
    prefixes: list[SidecarPrefix]
    full_models: list[str]
    connect_timeout_seconds: float
    request_timeout_seconds: float
    models_cache_ttl_seconds: float
    default_reasoning_effort: str | None


def openai_compat_provider_id(endpoint_id: str) -> str:
    return f"{OPENAI_COMPAT_PROVIDER_PREFIX}{endpoint_id}"


def openai_compat_account_id(endpoint_id: str) -> str:
    return f"{OPENAI_COMPAT_ACCOUNT_PREFIX}{endpoint_id}"


def is_openai_compat_provider(provider: str | None) -> bool:
    return bool(provider) and provider.startswith(OPENAI_COMPAT_PROVIDER_PREFIX)


def openai_compat_endpoint_id_from_provider(provider: str) -> str | None:
    if not is_openai_compat_provider(provider):
        return None
    return provider[len(OPENAI_COMPAT_PROVIDER_PREFIX) :]


def is_openai_compat_log_source(source: str | None) -> bool:
    return is_openai_compat_provider(source)


def parse_openai_compat_endpoints(raw: str | None) -> tuple[StoredOpenAICompatEndpoint, ...]:
    if not raw:
        return ()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return ()
    if not isinstance(parsed, list):
        return ()
    endpoints: list[StoredOpenAICompatEndpoint] = []
    seen_ids: set[str] = set()
    for entry in parsed:
        endpoint = _parse_stored_entry(entry)
        if endpoint is None or endpoint.id in seen_ids:
            continue
        seen_ids.add(endpoint.id)
        endpoints.append(endpoint)
    return tuple(endpoints)


def dump_openai_compat_endpoints(endpoints: tuple[StoredOpenAICompatEndpoint, ...]) -> str:
    payload: list[dict[str, Any]] = []
    for endpoint in endpoints:
        payload.append(
            {
                "id": endpoint.id,
                "name": endpoint.name,
                "enabled": endpoint.enabled,
                "base_url": endpoint.base_url,
                "api_key_encrypted": endpoint.api_key_encrypted_b64,
                "model_prefixes": [
                    {"prefix": prefix.prefix, "strip": prefix.strip} for prefix in endpoint.prefixes
                ],
                "full_models": list(endpoint.full_models),
                "connect_timeout_seconds": endpoint.connect_timeout_seconds,
                "request_timeout_seconds": endpoint.request_timeout_seconds,
                "models_cache_ttl_seconds": endpoint.models_cache_ttl_seconds,
                "default_reasoning_effort": endpoint.default_reasoning_effort,
                "last_health_status": endpoint.last_health_status,
                "last_health_message": endpoint.last_health_message,
                "last_checked_at": endpoint.last_checked_at.isoformat() if endpoint.last_checked_at else None,
                "last_model_count": endpoint.last_model_count,
            }
        )
    return json.dumps(payload, separators=(",", ":"))


def merge_openai_compat_endpoints(
    current_raw: str | None,
    incoming: list[OpenAICompatEndpointUpdateData],
    encryptor: TokenEncryptor,
) -> tuple[StoredOpenAICompatEndpoint, ...]:
    if len(incoming) > OPENAI_COMPAT_MAX_ENDPOINTS:
        raise ValueError(f"openai_compat_endpoints cannot exceed {OPENAI_COMPAT_MAX_ENDPOINTS} items")
    current_by_id = {endpoint.id: endpoint for endpoint in parse_openai_compat_endpoints(current_raw)}
    merged: list[StoredOpenAICompatEndpoint] = []
    seen_ids: set[str] = set()
    seen_names: set[str] = set()
    for item in incoming:
        endpoint_id = _require_endpoint_id(item.id)
        if endpoint_id in seen_ids:
            raise ValueError("openai_compat_endpoints ids must be unique")
        name = _require_name(item.name)
        name_key = name.casefold()
        if name_key in seen_names:
            raise ValueError("openai_compat_endpoints names must be unique")
        base_url = _require_base_url(item.base_url)
        existing = current_by_id.get(endpoint_id)
        encrypted_b64 = existing.api_key_encrypted_b64 if existing is not None else None
        if item.clear_api_key:
            encrypted_b64 = None
        elif item.api_key is not None:
            stripped = item.api_key.strip()
            encrypted_b64 = _encrypt_api_key(encryptor, stripped) if stripped else None
        merged.append(
            StoredOpenAICompatEndpoint(
                id=endpoint_id,
                name=name,
                enabled=bool(item.enabled),
                base_url=base_url,
                api_key_encrypted_b64=encrypted_b64,
                prefixes=tuple(item.prefixes),
                full_models=tuple(item.full_models),
                connect_timeout_seconds=_positive_timeout(
                    item.connect_timeout_seconds, _DEFAULT_CONNECT_TIMEOUT_SECONDS
                ),
                request_timeout_seconds=_positive_timeout(
                    item.request_timeout_seconds, _DEFAULT_REQUEST_TIMEOUT_SECONDS
                ),
                models_cache_ttl_seconds=_nonnegative_timeout(
                    item.models_cache_ttl_seconds, _DEFAULT_MODELS_CACHE_TTL_SECONDS
                ),
                default_reasoning_effort=item.default_reasoning_effort,
                last_health_status=existing.last_health_status if existing is not None else None,
                last_health_message=existing.last_health_message if existing is not None else None,
                last_checked_at=existing.last_checked_at if existing is not None else None,
                last_model_count=existing.last_model_count if existing is not None else None,
            )
        )
        seen_ids.add(endpoint_id)
        seen_names.add(name_key)
    return tuple(merged)


def decrypt_endpoint_api_key(
    endpoint: StoredOpenAICompatEndpoint,
    encryptor: TokenEncryptor | None = None,
) -> str | None:
    if not endpoint.api_key_encrypted_b64:
        return None
    try:
        raw = base64.b64decode(endpoint.api_key_encrypted_b64.encode("ascii"), validate=True)
    except (ValueError, UnicodeEncodeError):
        logger.warning("failed to decode OpenAI-compat API key for endpoint_id=%s", endpoint.id, exc_info=True)
        return None
    try:
        return (encryptor or TokenEncryptor()).decrypt(raw)
    except Exception:
        logger.warning("failed to decrypt OpenAI-compat API key for endpoint_id=%s", endpoint.id, exc_info=True)
        return None


def patch_endpoint_health(
    endpoints: tuple[StoredOpenAICompatEndpoint, ...],
    endpoint_id: str,
    *,
    last_health_status: str,
    last_health_message: str | None,
    last_checked_at: datetime,
    last_model_count: int | None,
) -> tuple[StoredOpenAICompatEndpoint, ...]:
    updated: list[StoredOpenAICompatEndpoint] = []
    found = False
    for endpoint in endpoints:
        if endpoint.id != endpoint_id:
            updated.append(endpoint)
            continue
        found = True
        updated.append(
            replace(
                endpoint,
                last_health_status=last_health_status,
                last_health_message=last_health_message,
                last_checked_at=last_checked_at,
                last_model_count=last_model_count,
            )
        )
    if not found:
        return endpoints
    return tuple(updated)


def _parse_stored_entry(entry: object) -> StoredOpenAICompatEndpoint | None:
    if not isinstance(entry, dict):
        return None
    endpoint_id = entry.get("id")
    if not isinstance(endpoint_id, str) or not _is_uuid(endpoint_id):
        return None
    name = entry.get("name")
    if not isinstance(name, str) or not name.strip():
        return None
    base_url = entry.get("base_url")
    if not isinstance(base_url, str) or not base_url.strip():
        return None
    try:
        normalized_url = _require_base_url(base_url)
    except ValueError:
        return None
    encrypted = entry.get("api_key_encrypted")
    encrypted_b64 = encrypted.strip() if isinstance(encrypted, str) and encrypted.strip() else None
    prefixes = parse_sidecar_prefixes(json.dumps(entry.get("model_prefixes") or []))
    full_models = parse_sidecar_full_models(json.dumps(entry.get("full_models") or []))
    checked_at = _parse_datetime(entry.get("last_checked_at"))
    last_model_count = entry.get("last_model_count")
    return StoredOpenAICompatEndpoint(
        id=endpoint_id,
        name=name.strip(),
        enabled=bool(entry.get("enabled")),
        base_url=normalized_url,
        api_key_encrypted_b64=encrypted_b64,
        prefixes=prefixes,
        full_models=full_models,
        connect_timeout_seconds=_positive_timeout(
            entry.get("connect_timeout_seconds"), _DEFAULT_CONNECT_TIMEOUT_SECONDS
        ),
        request_timeout_seconds=_positive_timeout(
            entry.get("request_timeout_seconds"), _DEFAULT_REQUEST_TIMEOUT_SECONDS
        ),
        models_cache_ttl_seconds=_nonnegative_timeout(
            entry.get("models_cache_ttl_seconds"), _DEFAULT_MODELS_CACHE_TTL_SECONDS
        ),
        default_reasoning_effort=_optional_str(entry.get("default_reasoning_effort")),
        last_health_status=_optional_str(entry.get("last_health_status")),
        last_health_message=_optional_str(entry.get("last_health_message")),
        last_checked_at=checked_at,
        last_model_count=last_model_count if isinstance(last_model_count, int) and last_model_count >= 0 else None,
    )


def _require_endpoint_id(value: str | None) -> str:
    if value and _is_uuid(value):
        return value
    if value:
        raise ValueError("openai_compat_endpoints id must be a UUID")
    return str(uuid4())


def _require_name(value: str) -> str:
    name = value.strip()
    if not name:
        raise ValueError("openai_compat_endpoints name must not be blank")
    if len(name) > 64:
        raise ValueError("openai_compat_endpoints name must be 64 characters or fewer")
    return name


def _require_base_url(value: str) -> str:
    """Validate and canonicalize a configured base URL at save time.

    Shape only: the whole point of this feature is that the host is arbitrary,
    so it cannot be pinned. The client re-runs the same normalizer immediately
    before putting the bearer token on the wire - see
    ``normalize_openai_compat_base_url`` for why each rejected shape changes the
    credential's destination. Validating in both places keeps a stored blob that
    predates this check (or was edited out of band) from reaching the network.
    """

    try:
        return normalize_openai_compat_base_url(value)
    except OpenAICompatBaseUrlError as exc:
        raise ValueError(f"openai_compat_endpoints {exc}") from exc


def _encrypt_api_key(encryptor: TokenEncryptor, plaintext: str) -> str:
    return base64.b64encode(encryptor.encrypt(plaintext)).decode("ascii")


def _is_uuid(value: str) -> bool:
    try:
        UUID(value)
    except ValueError:
        return False
    return True


def _optional_str(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        return parsed.replace(tzinfo=None)
    return parsed


def _positive_timeout(value: object, default: float) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return default
    if value <= 0:
        return default
    return float(value)


def _nonnegative_timeout(value: object, default: float) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return default
    if value < 0:
        return default
    return float(value)
