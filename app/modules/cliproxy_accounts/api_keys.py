"""API-key provider accounts stored in CLIProxyAPI's config lists.

OAuth credentials stay on the auth-file endpoints. These accounts are the
management lists CLIProxyAPI already edits: OpenAI-compatible providers
(OpenRouter and the same shape) and the Claude, Gemini, Codex, and xAI
API-key arrays. The panel never returns an API key to the browser. A prefix
already stored on an entry is sent back unchanged when the list is replaced,
unless the operator set a new one or the capacity router is filling an empty
prefix. Neither path clears a prefix.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from urllib.parse import urlsplit

from app.core.clients.claude_sidecar import ClaudeSidecarClient, ClaudeSidecarError
from app.core.exceptions import DashboardBadRequestError, DashboardConflictError
from app.core.types import JsonValue
from app.core.utils.json_guards import is_json_mapping
from app.modules.cliproxy_accounts.management import build_management
from app.modules.cliproxy_accounts.schemas import (
    CliproxyApiKeyAccount,
    CliproxyApiKeyModel,
    CliproxyCredential,
)
from app.modules.cliproxy_accounts.validation import validate_prefix

_MAX_MODEL_LENGTH = 200
_MAX_NAME_LENGTH = 64
_MAX_SECRET_LENGTH = 4_096


@dataclass(frozen=True, slots=True)
class ApiKeyKind:
    slug: str
    path: str
    response_key: str
    supports_disable: bool
    named: bool


API_KEY_KINDS: dict[str, ApiKeyKind] = {
    "openai-compatibility": ApiKeyKind(
        slug="openai-compatibility",
        path="/v0/management/openai-compatibility",
        response_key="openai-compatibility",
        supports_disable=True,
        named=True,
    ),
    "claude": ApiKeyKind(
        slug="claude",
        path="/v0/management/claude-api-key",
        response_key="claude-api-key",
        supports_disable=False,
        named=False,
    ),
    "gemini": ApiKeyKind(
        slug="gemini",
        path="/v0/management/gemini-api-key",
        response_key="gemini-api-key",
        supports_disable=False,
        named=False,
    ),
    "codex": ApiKeyKind(
        slug="codex",
        path="/v0/management/codex-api-key",
        response_key="codex-api-key",
        supports_disable=False,
        named=False,
    ),
    "xai": ApiKeyKind(
        slug="xai",
        path="/v0/management/xai-api-key",
        response_key="xai-api-key",
        supports_disable=False,
        named=False,
    ),
}


@dataclass(frozen=True, slots=True)
class ApiKeyWrite:
    kind: str
    name: str | None
    base_url: str
    api_key: str | None
    models: tuple[str, ...]
    disabled: bool | None
    update_models: bool
    update_disabled: bool
    update_name: bool
    prefix: str | None = None
    update_prefix: bool = False


def api_key_kind(slug: str) -> ApiKeyKind:
    kind = API_KEY_KINDS.get(slug.strip().lower())
    if kind is None:
        raise DashboardBadRequestError("That API-key provider is not supported")
    return kind


def normalize_api_key_write(
    *,
    kind: str,
    name: str | None,
    base_url: str,
    api_key: str | None,
    models: Sequence[str] | None,
    disabled: bool | None,
    update_models: bool,
    update_disabled: bool,
    creating: bool,
    prefix: str | None = None,
    update_prefix: bool = False,
) -> ApiKeyWrite:
    resolved = api_key_kind(kind)
    label, update_name = _name_for_write(resolved, name, creating=creating)
    url = _base_url(base_url)
    secret = _optional_secret(api_key)
    if creating and not secret:
        raise DashboardBadRequestError("API key is required")
    model_ids = _models(models or ()) if update_models or creating else ()
    if update_disabled and disabled is not None and not resolved.supports_disable:
        raise DashboardBadRequestError("This provider has no on/off switch")
    stored_prefix = validate_prefix(prefix) if update_prefix else None
    return ApiKeyWrite(
        kind=resolved.slug,
        name=label,
        base_url=url,
        api_key=secret,
        models=model_ids,
        disabled=disabled,
        update_models=update_models or creating,
        update_disabled=update_disabled and resolved.supports_disable,
        update_name=update_name,
        prefix=stored_prefix,
        update_prefix=update_prefix and not creating,
    )


async def list_api_key_accounts(
    client: ClaudeSidecarClient,
    raw_files: Sequence[Mapping[str, JsonValue]],
) -> tuple[list[CliproxyApiKeyAccount], str | None]:
    """Read every supported API-key list. A missing endpoint is an empty kind."""

    accounts: list[CliproxyApiKeyAccount] = []
    messages: list[str] = []
    for kind in API_KEY_KINDS.values():
        try:
            payload = await _request(client, "GET", kind.path, None)
        except ClaudeSidecarError as exc:
            if exc.status_code == 404:
                continue
            messages.append(exc.message)
            continue
        for index, item in enumerate(_items(payload, kind.response_key)):
            if not is_json_mapping(item):
                continue
            accounts.append(await _project(client, kind, index, item, raw_files))
    message = messages[0] if messages else None
    return accounts, message


async def create_api_key_account(
    client: ClaudeSidecarClient,
    raw_files: Sequence[Mapping[str, JsonValue]],
    write: ApiKeyWrite,
) -> CliproxyApiKeyAccount:
    kind = api_key_kind(write.kind)
    payload = await _request(client, "GET", kind.path, None)
    items = [dict(item) for item in _items(payload, kind.response_key) if is_json_mapping(item)]
    items.append(_new_item(kind, write))
    stored = await _request(client, "PUT", kind.path, {"items": items})
    saved = [item for item in _items(stored, kind.response_key) if is_json_mapping(item)] or items
    index = len(saved) - 1
    return await _project(client, kind, index, saved[index], raw_files)


async def update_api_key_account(
    client: ClaudeSidecarClient,
    raw_files: Sequence[Mapping[str, JsonValue]],
    index: int,
    write: ApiKeyWrite,
    account_id: str,
) -> CliproxyApiKeyAccount:
    kind = api_key_kind(write.kind)
    payload = await _request(client, "GET", kind.path, None)
    items = [dict(item) for item in _items(payload, kind.response_key) if is_json_mapping(item)]
    current = _require_account(kind, items, index, account_id)
    if write.update_prefix and write.prefix:
        for offset, item in enumerate(items):
            if offset == index:
                continue
            if (_text(item.get("prefix")) or "").casefold() == write.prefix.casefold():
                raise DashboardConflictError("That prefix is already used by another CLIProxyAPI account")
    items[index] = _edited_item(kind, current, write)
    stored = await _request(client, "PUT", kind.path, {"items": items})
    saved = [item for item in _items(stored, kind.response_key) if is_json_mapping(item)] or items
    if index >= len(saved):
        raise DashboardConflictError(_STALE_ACCOUNT)
    return await _project(client, kind, index, saved[index], raw_files)


@dataclass(frozen=True, slots=True)
class ApiKeyRouteRow:
    """One API-key entry the capacity router can pin, without the secret."""

    kind: str
    index: int
    name: str
    prefix: str | None
    disabled: bool
    models: tuple[str, ...]
    auth_index: str | None
    weight: int | None
    priority: int | None
    route_identity: str


async def list_routing_api_keys(client: ClaudeSidecarClient) -> list[ApiKeyRouteRow]:
    """Return API-key rows for capacity routing, omitting the key material."""

    rows: list[ApiKeyRouteRow] = []
    for kind in API_KEY_KINDS.values():
        try:
            payload = await _request(client, "GET", kind.path, None)
        except ClaudeSidecarError as exc:
            if exc.status_code == 404:
                continue
            raise
        for index, item in enumerate(_items(payload, kind.response_key)):
            if not is_json_mapping(item):
                continue
            models = tuple(
                text
                for model in _configured_models(item.get("models"))
                if (text := model.alias.strip() or model.name.strip())
            )
            rows.append(
                ApiKeyRouteRow(
                    kind=kind.slug,
                    index=index,
                    name=_text(item.get("name")) or _text(item.get("id")) or f"{kind.slug}:{index}",
                    prefix=_text(item.get("prefix")),
                    disabled=bool(item.get("disabled")) if kind.supports_disable else False,
                    models=models,
                    auth_index=_text(item.get("auth-index")) or _text(item.get("auth_index")),
                    weight=_optional_int(item.get("weight")),
                    priority=_optional_int(item.get("priority")),
                    route_identity=api_key_route_identity(kind, item),
                )
            )
    return rows


async def stored_api_key_prefixes(
    client: ClaudeSidecarClient,
    *,
    skip: tuple[str, int] | None = None,
) -> list[str]:
    """Return prefixes currently stored on API-key entries.

    ``skip`` is ``(kind, index)`` for the entry being edited, so its own
    prefix is not treated as a collision.
    """

    found: list[str] = []
    for kind in API_KEY_KINDS.values():
        try:
            payload = await _request(client, "GET", kind.path, None)
        except ClaudeSidecarError as exc:
            if exc.status_code == 404:
                continue
            raise
        for index, item in enumerate(_items(payload, kind.response_key)):
            if skip is not None and skip == (kind.slug, index):
                continue
            if not is_json_mapping(item):
                continue
            prefix = _text(item.get("prefix"))
            if prefix:
                found.append(prefix)
    return found


async def set_api_key_prefix_if_empty(
    client: ClaudeSidecarClient,
    *,
    kind_slug: str,
    route_identity: str,
    prefix: str,
) -> str | None:
    """Write ``prefix`` only when the entry with ``route_identity`` has none.

    The caller holds the prefix lock and this provider's list lock. The live
    list is searched by identity, not by a cached index, so a deletion that
    shifts the list cannot receive another credential's prefix. A prefix that
    is already stored on the matching entry is returned unchanged. ``None``
    means that identity is no longer in the list.
    """

    kind = api_key_kind(kind_slug)
    payload = await _request(client, "GET", kind.path, None)
    items = [dict(item) for item in _items(payload, kind.response_key) if is_json_mapping(item)]
    match = next(
        (index for index, item in enumerate(items) if api_key_route_identity(kind, item) == route_identity),
        None,
    )
    if match is None:
        return None
    existing = _text(items[match].get("prefix"))
    if existing:
        return existing
    items[match]["prefix"] = prefix
    await _request(client, "PUT", kind.path, {"items": items})
    return prefix


async def delete_api_key_account(
    client: ClaudeSidecarClient,
    kind_slug: str,
    index: int,
    account_id: str,
) -> None:
    kind = api_key_kind(kind_slug)
    payload = await _request(client, "GET", kind.path, None)
    items = [item for item in _items(payload, kind.response_key) if is_json_mapping(item)]
    _require_account(kind, items, index, account_id)
    await _request(client, "DELETE", f"{kind.path}?index={index}", None)


def shared_model_ids(
    credentials: Sequence[CliproxyCredential],
    api_keys: Sequence[CliproxyApiKeyAccount],
) -> list[str]:
    """Model ids served by more than one CLIProxyAPI account.

    CLIProxyAPI load-balances one client-facing id across the accounts that
    register it, including accounts on different providers.
    """

    owners: dict[str, set[str]] = {}
    labels: dict[str, str] = {}

    def add(owner: str, model: str) -> None:
        text = model.strip()
        if not text:
            return
        key = text.casefold()
        labels.setdefault(key, text)
        owners.setdefault(key, set()).add(owner)

    for credential in credentials:
        owner = f"oauth:{credential.provider}:{credential.auth_index or credential.name}"
        for model in credential.models:
            add(owner, model)
    for account in api_keys:
        owner = f"key:{account.kind}:{account.index}"
        discovered = account.discovered_models or [model.alias or model.name for model in account.models]
        for model in discovered:
            add(owner, model)
    return [labels[key] for key in sorted(labels) if len(owners.get(key, ())) > 1]


async def _project(
    client: ClaudeSidecarClient,
    kind: ApiKeyKind,
    index: int,
    item: Mapping[str, JsonValue],
    raw_files: Sequence[Mapping[str, JsonValue]],
) -> CliproxyApiKeyAccount:
    auth_index = _text(item.get("auth-index"))
    prefix = _text(item.get("prefix"))
    configured = _configured_models(item.get("models"))
    discovered, models_error = await _discovered_models(client, auth_index, raw_files)
    disabled = item.get("disabled") if kind.supports_disable and isinstance(item.get("disabled"), bool) else None
    name = _text(item.get("name")) if kind.named else None
    return CliproxyApiKeyAccount(
        id=api_key_account_id(kind, item),
        kind=kind.slug,
        index=index,
        name=name or _fallback_name(kind, index),
        base_url=_text(item.get("base-url")) or "",
        disabled=disabled,
        supports_disable=kind.supports_disable,
        has_api_key=_has_api_key(kind, item),
        models=configured,
        discovered_models=discovered,
        models_error=models_error,
        auth_index=auth_index,
        prefix=prefix,
        weight=_optional_int(item.get("weight")),
        priority=_optional_int(item.get("priority")),
    )


async def _discovered_models(
    client: ClaudeSidecarClient,
    auth_index: str | None,
    raw_files: Sequence[Mapping[str, JsonValue]],
) -> tuple[list[str], str | None]:
    if not auth_index:
        return [], None
    match = _auth_file_for_index(raw_files, auth_index)
    if match is None:
        return [], None
    name = _text(match.get("id")) or _text(match.get("name"))
    if not name:
        return [], None
    try:
        return await client.list_auth_file_models(name), None
    except ClaudeSidecarError as exc:
        return [], exc.message


def _auth_file_for_index(
    raw_files: Sequence[Mapping[str, JsonValue]],
    auth_index: str,
) -> Mapping[str, JsonValue] | None:
    for entry in raw_files:
        if not is_json_mapping(entry):
            continue
        if _text(entry.get("auth_index")) == auth_index:
            return entry
    return None


def _new_item(kind: ApiKeyKind, write: ApiKeyWrite) -> dict[str, JsonValue]:
    models = _model_payload(write.models)
    if kind.named:
        item: dict[str, JsonValue] = {
            "name": write.name or "",
            "base-url": write.base_url,
            "api-key-entries": [{"api-key": write.api_key or ""}],
            "models": models,
        }
        if write.disabled is not None:
            item["disabled"] = write.disabled
        return item
    return {
        "api-key": write.api_key or "",
        "base-url": write.base_url,
        "models": models,
    }


def _edited_item(kind: ApiKeyKind, current: Mapping[str, JsonValue], write: ApiKeyWrite) -> dict[str, JsonValue]:
    """Copy the stored entry, then change only the fields the form sent.

    ``prefix`` and every other untouched field stay as CLIProxyAPI stored them.
    """

    updated = dict(current)
    updated["base-url"] = write.base_url
    if kind.named and write.update_name:
        updated["name"] = _kept_or_new_name(current, write.name or "")
    if write.update_models:
        updated["models"] = _merged_model_payload(current.get("models"), write.models)
    if write.api_key:
        if kind.named:
            updated["api-key-entries"] = _replace_first_key(current.get("api-key-entries"), write.api_key)
        else:
            updated["api-key"] = write.api_key
    if write.update_disabled and write.disabled is not None:
        updated["disabled"] = write.disabled
    if write.update_prefix and write.prefix:
        updated["prefix"] = write.prefix
    return updated


def _replace_first_key(raw: JsonValue | None, api_key: str) -> list[JsonValue]:
    entries: list[JsonValue] = []
    if isinstance(raw, list):
        entries = [dict(entry) if is_json_mapping(entry) else entry for entry in raw]
    if not entries:
        return [{"api-key": api_key}]
    first = entries[0]
    if is_json_mapping(first):
        replaced = dict(first)
        replaced["api-key"] = api_key
        entries[0] = replaced
        return entries
    return [{"api-key": api_key}, *entries[1:]]


_STALE_ACCOUNT = "This API-key account changed before the edit was saved. Reload and try again."
_ACCOUNT_ID_KEY = b"codex-lb.cliproxy-api-key-account.v1"


def api_key_account_id(kind: ApiKeyKind, item: Mapping[str, JsonValue]) -> str:
    """Opaque identity of one stored entry.

    Edit and delete send this token back. The write checks the entry currently
    at the requested index and rejects the request when the token does not
    match, so a stale page cannot land on a neighbor after the list shifts.
    The token mixes the public entry with a keyed digest of the stored API
    key. Two entries that share a URL, name, and model list still differ when
    their keys differ, and the key itself is not in the token. The list index
    is not part of the token: moving an entry must not make it match a neighbor.
    """

    payload = _identity_payload(kind, item)
    payload["prefix"] = _text(item.get("prefix")) or ""
    return _identity_digest(payload)


def api_key_route_identity(kind: ApiKeyKind, item: Mapping[str, JsonValue]) -> str:
    """Routing identity that stays put when only the credential prefix changes.

    Dashboard edits keep using :func:`api_key_account_id`, which includes the
    prefix the operator was looking at. Prefix fill must not treat that change
    as a different credential, and it must not trust the list index.
    """

    return _identity_digest(_identity_payload(kind, item))


def _identity_payload(kind: ApiKeyKind, item: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
    disabled = item.get("disabled") if kind.supports_disable and isinstance(item.get("disabled"), bool) else None
    return {
        "authIndex": _text(item.get("auth-index")) or "",
        "baseUrl": _text(item.get("base-url")) or "",
        "credential": _credential_digest(kind, item),
        "disabled": disabled,
        "kind": kind.slug,
        "models": [{"alias": model.alias, "name": model.name} for model in _configured_models(item.get("models"))],
        "name": (_text(item.get("name")) or "") if kind.named else "",
    }


def _identity_digest(payload: Mapping[str, JsonValue]) -> str:
    encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(encoded.encode()).hexdigest()


def _credential_digest(kind: ApiKeyKind, item: Mapping[str, JsonValue]) -> str:
    encoded = json.dumps(_credential_secrets(kind, item), separators=(",", ":"), ensure_ascii=False)
    return hmac.new(_ACCOUNT_ID_KEY, encoded.encode(), hashlib.sha256).hexdigest()


def _credential_secrets(kind: ApiKeyKind, item: Mapping[str, JsonValue]) -> list[str]:
    if kind.named:
        entries = item.get("api-key-entries")
        if not isinstance(entries, list):
            return []
        secrets: list[str] = []
        for entry in entries:
            if is_json_mapping(entry):
                secrets.append(_text(entry.get("api-key")) or "")
            elif isinstance(entry, str):
                secrets.append(entry.strip())
        return secrets
    return [_text(item.get("api-key")) or ""]


def _require_account(
    kind: ApiKeyKind,
    items: Sequence[Mapping[str, JsonValue]],
    index: int,
    account_id: str,
) -> Mapping[str, JsonValue]:
    if index < 0 or index >= len(items) or api_key_account_id(kind, items[index]) != account_id:
        raise DashboardConflictError(_STALE_ACCOUNT)
    return items[index]


def _name_for_write(kind: ApiKeyKind, name: str | None, *, creating: bool) -> tuple[str | None, bool]:
    if not kind.named:
        return None, False
    if name is None:
        if creating:
            raise DashboardBadRequestError("Name is required")
        return None, False
    text = name.strip()
    if not text:
        raise DashboardBadRequestError("Name is required")
    if len(text) > _MAX_NAME_LENGTH or "/" in text or "\\" in text:
        raise DashboardBadRequestError("Name must be a single short label")
    if creating:
        label = _optional_name(text)
        if label is None:
            raise DashboardBadRequestError("Name must be a single short label")
        return label, True
    return text, True


def _kept_or_new_name(current: Mapping[str, JsonValue], submitted: str) -> str:
    stored = _text(current.get("name"))
    if stored is not None and submitted == stored:
        return stored
    label = _optional_name(submitted)
    if label is None:
        raise DashboardBadRequestError("Name must be a single short label")
    return label


def _model_payload(models: Sequence[str]) -> list[JsonValue]:
    return [{"name": model, "alias": model} for model in models]


def _merged_model_payload(raw: JsonValue | None, models: Sequence[str]) -> list[JsonValue]:
    """Keep stored name/alias pairs for client ids the form still lists.

    Submitted ids are matched by alias, then by upstream name. A matched
    upstream name is not treated as another submitted id, so an alias that
    equals a different mapping's upstream name stays in the list. The same
    stored mapping is emitted once. A new id becomes an identity mapping.
    An omitted models field never calls this, so a URL or key change leaves
    the stored mappings alone.
    """

    existing = _configured_models(raw)
    by_alias: dict[str, CliproxyApiKeyModel] = {}
    by_name: dict[str, CliproxyApiKeyModel] = {}
    for model in existing:
        by_alias.setdefault(model.alias.casefold(), model)
        by_name.setdefault(model.name.casefold(), model)
    merged: list[JsonValue] = []
    seen_ids: set[str] = set()
    selected: set[tuple[str, str]] = set()
    for model_id in models:
        key = model_id.casefold()
        if key in seen_ids:
            continue
        seen_ids.add(key)
        match = by_alias.get(key) or by_name.get(key)
        if match is None:
            merged.append({"name": model_id, "alias": model_id})
            continue
        identity = (match.name.casefold(), match.alias.casefold())
        if identity in selected:
            continue
        selected.add(identity)
        merged.append({"name": match.name, "alias": match.alias})
    return merged


def _configured_models(raw: JsonValue | None) -> list[CliproxyApiKeyModel]:
    if not isinstance(raw, list):
        return []
    models: list[CliproxyApiKeyModel] = []
    for entry in raw:
        if isinstance(entry, str) and entry.strip():
            models.append(CliproxyApiKeyModel(name=entry.strip(), alias=entry.strip()))
            continue
        if not is_json_mapping(entry):
            continue
        name = _text(entry.get("name"))
        alias = _text(entry.get("alias")) or name
        if name or alias:
            models.append(CliproxyApiKeyModel(name=name or alias or "", alias=alias or name or ""))
    return models


def _has_api_key(kind: ApiKeyKind, item: Mapping[str, JsonValue]) -> bool:
    if kind.named:
        entries = item.get("api-key-entries")
        if not isinstance(entries, list):
            return False
        return any(is_json_mapping(entry) and bool(_text(entry.get("api-key"))) for entry in entries)
    return bool(_text(item.get("api-key")))


def _items(payload: Mapping[str, JsonValue], key: str) -> list[JsonValue]:
    keyed = payload.get(key)
    if isinstance(keyed, list):
        return list(keyed)
    wrapped = payload.get("items")
    if isinstance(wrapped, list):
        return list(wrapped)
    return []


def _fallback_name(kind: ApiKeyKind, index: int) -> str:
    label = {
        "openai-compatibility": "OpenAI-compatible",
        "claude": "Claude",
        "gemini": "Gemini",
        "codex": "Codex",
        "xai": "xAI",
    }.get(kind.slug, kind.slug)
    return f"{label} API key {index + 1}"


async def _request(
    client: ClaudeSidecarClient,
    method: str,
    path: str,
    body: Mapping[str, JsonValue] | None,
) -> Mapping[str, JsonValue]:
    custom = getattr(client, "management_request", None)
    if custom is not None:
        payload = await custom(method, path, body)
        if payload is None:
            return {}
        if not is_json_mapping(payload):
            raise ClaudeSidecarError(502, "CLIProxyAPI returned a response the panel cannot read")
        return payload
    management = build_management(client)
    if method == "GET":
        return await management.get_json(path)
    if method == "PUT":
        return await management.put_json(path, body or {})
    if method == "DELETE":
        await management.delete_path(path)
        return {}
    raise ClaudeSidecarError(500, "Unsupported management method")


def _optional_name(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    if len(text) > _MAX_NAME_LENGTH or "/" in text or "\\" in text or any(char.isspace() for char in text):
        return None
    return text


def _base_url(value: str) -> str:
    text = value.strip()
    parts = urlsplit(text)
    if parts.scheme not in {"http", "https"} or not parts.netloc or any(char.isspace() for char in text):
        raise DashboardBadRequestError("Base URL must be an http or https URL")
    if len(text) > 500:
        raise DashboardBadRequestError("Base URL is too long")
    return text


def _optional_secret(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    if len(text) > _MAX_SECRET_LENGTH or any(char.isspace() for char in text):
        raise DashboardBadRequestError("API key must be a single token")
    return text


def _models(values: Sequence[str]) -> tuple[str, ...]:
    models: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = value.strip()
        if not text:
            continue
        if len(text) > _MAX_MODEL_LENGTH or any(char.isspace() for char in text):
            raise DashboardBadRequestError("Each model id must be a single token")
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        models.append(text)
    return tuple(models)


def _optional_int(value: JsonValue | None) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _text(value: JsonValue | None) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None
