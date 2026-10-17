"""Validate an operator-supplied CLIProxyAPI credential file before upload.

A prefix already in the file is forwarded unchanged. The panel does not
assign one and does not strip one the file already has.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass

from app.core.exceptions import DashboardBadRequestError
from app.core.types import JsonValue
from app.core.utils.json_guards import is_json_mapping
from app.modules.cliproxy_accounts.providers import UPLOAD_TYPES
from app.modules.cliproxy_accounts.validation import (
    validate_excluded_models,
    validate_priority,
    validate_weight,
)

MAX_UPLOAD_BYTES = 256 * 1024
_CREDENTIAL_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._@-]*\.json$")
_STRING_KEYS = frozenset(
    {
        "access_token",
        "account_id",
        "account_uuid",
        "auth_kind",
        "base_url",
        "email",
        "expired",
        "id_token",
        "last_refresh",
        "organization_name",
        "organization_uuid",
        "redirect_uri",
        "refresh_token",
        "sub",
        "token_endpoint",
        "token_type",
        "type",
    }
)
_MAX_STRING = 16_384


@dataclass(frozen=True, slots=True)
class PreparedUpload:
    provider: str
    body: bytes
    prefix: str | None


def normalize_credential_name(name: str) -> str:
    trimmed = name.strip()
    if (
        not trimmed
        or len(trimmed) > 200
        or "/" in trimmed
        or "\\" in trimmed
        or ".." in trimmed
        or _CREDENTIAL_NAME.fullmatch(trimmed) is None
    ):
        raise DashboardBadRequestError("Credential name must be a single .json file name")
    return trimmed


def prepare_upload_document(document: str) -> PreparedUpload:
    if len(document.encode("utf-8")) > MAX_UPLOAD_BYTES:
        raise DashboardBadRequestError("Credential file is too large")
    try:
        parsed = json.loads(document)
    except json.JSONDecodeError as exc:
        raise DashboardBadRequestError("Credential file must be JSON") from exc
    if not is_json_mapping(parsed):
        raise DashboardBadRequestError("Credential file must be a JSON object")
    return _prepare_object(parsed)


def _prepare_object(parsed: Mapping[str, JsonValue]) -> PreparedUpload:
    unknown = sorted(key for key in parsed if key not in _STRING_KEYS | _METADATA_KEYS)
    if unknown:
        raise DashboardBadRequestError(
            "Credential file contains fields the panel cannot validate: " + ", ".join(unknown)
        )
    provider = _provider(parsed.get("type"))
    prefix = _prefix(parsed.get("prefix")) if "prefix" in parsed else None
    payload: dict[str, JsonValue] = {"type": provider}
    for key in _STRING_KEYS:
        if key == "type" or key not in parsed:
            continue
        payload[key] = _string_field(key, parsed[key])
    if "expires_in" in parsed:
        payload["expires_in"] = _expires_in(parsed["expires_in"])
    if "disabled" in parsed:
        payload["disabled"] = _disabled(parsed["disabled"])
    if "weight" in parsed:
        payload["weight"] = validate_weight(_json_int("weight", parsed["weight"]))
    if "priority" in parsed:
        payload["priority"] = validate_priority(_json_int("priority", parsed["priority"]))
    if "excluded_models" in parsed:
        payload["excluded_models"] = list(_excluded(parsed["excluded_models"]))
    if "note" in parsed:
        payload["note"] = _note(parsed["note"])
    if prefix is not None:
        payload["prefix"] = prefix
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return PreparedUpload(provider=provider, body=body, prefix=prefix)


_METADATA_KEYS = frozenset({"prefix", "weight", "priority", "excluded_models", "disabled", "note", "expires_in"})


def _provider(value: JsonValue | None) -> str:
    if not isinstance(value, str) or value.strip().lower() not in UPLOAD_TYPES:
        raise DashboardBadRequestError("Credential file type is not a provider the panel can validate")
    return value.strip().lower()


def _prefix(value: JsonValue | None) -> str:
    if not isinstance(value, str):
        raise DashboardBadRequestError("Prefix must be a string")
    text = value.strip()
    if not text or len(text) > 128 or "/" in text or "\\" in text or any(char.isspace() for char in text):
        raise DashboardBadRequestError("Prefix must be a single segment")
    return text


def _string_field(key: str, value: JsonValue | None) -> str:
    if not isinstance(value, str):
        raise DashboardBadRequestError(f"{key} must be a string")
    if len(value) > _MAX_STRING:
        raise DashboardBadRequestError(f"{key} is too long")
    return value


def _expires_in(value: JsonValue | None) -> int:
    number = _json_int("expires_in", value)
    if number < 0 or number > 86_400 * 365:
        raise DashboardBadRequestError("expires_in is out of range")
    return number


def _disabled(value: JsonValue | None) -> bool:
    if not isinstance(value, bool):
        raise DashboardBadRequestError("disabled must be true or false")
    return value


def _excluded(value: JsonValue | None) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise DashboardBadRequestError("Excluded models must be a list of strings")
    return validate_excluded_models(value)


def _note(value: JsonValue | None) -> str:
    if not isinstance(value, str):
        raise DashboardBadRequestError("note must be a string")
    trimmed = value.strip()
    if len(trimmed) > 500:
        raise DashboardBadRequestError("note is too long")
    return trimmed


def _json_int(key: str, value: JsonValue | None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise DashboardBadRequestError(f"{key} must be an integer")
    return value
