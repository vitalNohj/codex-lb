"""API-key provider accounts stored in CLIProxyAPI's ``api-keys`` config.

OAuth credentials stay on the auth-file endpoints. These accounts are the
``api-keys`` groups in CLIProxyAPI's v8 config: OpenAI-compatible providers
(OpenRouter and the same shape) and the Claude, Gemini, Codex, and xAI key
families. The panel never returns an API key to the browser.

Every read and write goes through CLIProxyAPI's v8 config API
(``/v8/management/config/api-keys``), which edits the raw YAML tree. The
older per-family ``/v0/management/<kind>-api-key`` endpoints are not used:
a v0 write is converted back into v8 layout by CLIProxyAPI, which renames
every group in the family to ``<provider>-<n>`` and splits multi-key groups
into one group per key (CLIProxyAPI ``groupLegacyKeys``). That conversion
runs on ``PUT``, ``PATCH``, and ``DELETE`` alike. A v8 write replaces only one
family's list, built here from the list just read, so group names, shared
fields, per-key overrides, and unknown fields survive. Each write sends the
read's ``ETag`` back in ``If-Match``. CLIProxyAPI refuses a write when the file
changed after the read, and the whole edit is redone on the fresh list.

An account is one routable CLIProxyAPI credential. For the Claude, Gemini,
Codex, and xAI families that is one key inside a group. CLIProxyAPI expands
each key into its own credential, so a group with three keys is three
accounts. For ``openai-compatibility``, CLIProxyAPI registers the whole group
as one provider and spreads requests across the group's keys, so the group
is one account. ``index`` is the account's position in CLIProxyAPI's legacy
expansion, which is also the v0 list index.
"""

from __future__ import annotations

import copy
import hashlib
import hmac
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from urllib.parse import urlsplit

from app.core.clients.claude_sidecar import ClaudeSidecarClient, ClaudeSidecarError
from app.core.exceptions import DashboardBadRequestError, DashboardConflictError
from app.core.types import JsonValue
from app.core.utils.json_guards import is_json_mapping
from app.modules.cliproxy_accounts.management import ManagementResponse, build_management, error_message
from app.modules.cliproxy_accounts.schemas import (
    CliproxyApiKeyAccount,
    CliproxyApiKeyModel,
    CliproxyCredential,
)
from app.modules.cliproxy_accounts.validation import validate_prefix

_MAX_MODEL_LENGTH = 200
_MAX_NAME_LENGTH = 64
_MAX_SECRET_LENGTH = 4_096
_CONFIG_PATH = "/v8/management/config/api-keys"
_WRITE_ATTEMPTS = 4


@dataclass(frozen=True, slots=True)
class ApiKeyKind:
    slug: str
    family: str
    seed_kind: str
    supports_disable: bool
    named: bool


API_KEY_KINDS: dict[str, ApiKeyKind] = {
    "openai-compatibility": ApiKeyKind(
        slug="openai-compatibility",
        family="openai-compatibility",
        seed_kind="openai-compatibility",
        supports_disable=True,
        named=True,
    ),
    "claude": ApiKeyKind(
        slug="claude",
        family="claude",
        seed_kind="claude-api-key",
        supports_disable=False,
        named=False,
    ),
    "gemini": ApiKeyKind(
        slug="gemini",
        family="gemini",
        seed_kind="gemini-api-key",
        supports_disable=False,
        named=False,
    ),
    "codex": ApiKeyKind(
        slug="codex",
        family="codex",
        seed_kind="codex-api-key",
        supports_disable=False,
        named=False,
    ),
    "xai": ApiKeyKind(
        slug="xai",
        family="xai",
        seed_kind="xai-api-key",
        supports_disable=False,
        named=False,
    ),
}

# Fields a v8 key group shares with every key in it. A key may override any
# of them; a null override inherits the group value. Mirrors CLIProxyAPI's
# ``sharedKeyFields`` in ``internal/config/config_v8.go``.
_SHARED_KEY_FIELDS = frozenset(
    {
        "priority",
        "prefix",
        "proxy-url",
        "headers",
        "models",
        "excluded-models",
        "disable-cooling",
        "request-retry",
        "request-scoped-errors",
    }
)
_AUTH_INDEX_FIELDS = ("auth_index", "auth-index")


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
    support_prompt_cache_key: bool | None = None
    update_support_prompt_cache_key: bool = False


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
    support_prompt_cache_key: bool | None = None,
    update_support_prompt_cache_key: bool = False,
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
    if update_support_prompt_cache_key and support_prompt_cache_key is not None and not resolved.named:
        raise DashboardBadRequestError("Only OpenAI-compatible providers accept prompt cache keys")
    stored_prefix = validate_prefix(prefix or "") if update_prefix else None
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
        support_prompt_cache_key=support_prompt_cache_key,
        update_support_prompt_cache_key=(
            update_support_prompt_cache_key and resolved.named and support_prompt_cache_key is not None
        ),
    )


# --- v8 config tree --------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Entry:
    """One routable credential in a family's v8 group list.

    ``key_pos`` is ``None`` for an openai-compatibility group, which
    CLIProxyAPI routes as one provider across all of its keys.
    """

    index: int
    group_pos: int
    key_pos: int | None
    item: dict[str, JsonValue]


@dataclass(slots=True)
class _ApiKeyConfig:
    families: dict[str, list[JsonValue]]
    etag: str | None


async def _read_config(client: ClaudeSidecarClient) -> _ApiKeyConfig:
    response = await _config_call(client, "GET", _CONFIG_PATH, None, None)
    if response.status == 404:
        if is_json_mapping(response.body) and response.body.get("error") == "not_found":
            return _ApiKeyConfig(families={}, etag=response.etag)
        raise ClaudeSidecarError(
            502,
            "CLIProxyAPI has no v8 config API. Upgrade CLIProxyAPI to v8 to edit API-key accounts safely.",
        )
    if response.status != 200:
        raise ClaudeSidecarError(response.status, error_message(response.status, response.body), body=response.body)
    if not is_json_mapping(response.body):
        raise ClaudeSidecarError(502, "CLIProxyAPI returned API-key config the panel cannot read")
    families: dict[str, list[JsonValue]] = {}
    for kind in API_KEY_KINDS.values():
        raw = response.body.get(kind.family)
        if isinstance(raw, list):
            families[kind.family] = copy.deepcopy(list(raw))
    return _ApiKeyConfig(families=families, etag=response.etag)


async def _write_family(
    client: ClaudeSidecarClient,
    kind: ApiKeyKind,
    groups: list[JsonValue],
    etag: str | None,
) -> bool:
    """Replace one family's group list. ``False`` means the file changed since the read."""

    body = [_strip_auth_indexes(group) for group in groups]
    response = await _config_call(client, "PUT", f"{_CONFIG_PATH}/{kind.family}", body, etag)
    if response.status == 412:
        return False
    if response.status != 200:
        raise ClaudeSidecarError(response.status, error_message(response.status, response.body), body=response.body)
    return True


async def _config_call(
    client: ClaudeSidecarClient,
    method: str,
    path: str,
    body: JsonValue | None,
    if_match: str | None,
) -> ManagementResponse:
    custom = getattr(client, "config_v8_request", None)
    if custom is not None:
        return await custom(method, path, body, if_match)
    return await build_management(client).config_v8(method, path, body=body, if_match=if_match)


async def _edit_family[T](
    client: ClaudeSidecarClient,
    kind: ApiKeyKind,
    edit: Callable[[_ApiKeyConfig, list[JsonValue]], tuple[list[JsonValue] | None, T]],
) -> T:
    """Read, edit, and write one family, redoing the edit when another writer won.

    ``edit`` gets the whole config (so it can check other families) and a
    private copy of this family's groups. It returns the new groups, or
    ``None`` to skip the write, plus its result.
    """

    for _attempt in range(_WRITE_ATTEMPTS):
        config = await _read_config(client)
        groups = copy.deepcopy(config.families.get(kind.family, []))
        updated, result = edit(config, groups)
        if updated is None:
            return result
        if await _write_family(client, kind, updated, config.etag):
            return result
    raise DashboardConflictError("CLIProxyAPI's API-key config kept changing during the edit. Try again.")


def _entries(kind: ApiKeyKind, groups: Sequence[JsonValue]) -> list[_Entry]:
    """Expand v8 groups into legacy entries, in CLIProxyAPI's ``expandV8Groups`` order."""

    entries: list[_Entry] = []
    for group_pos, group in enumerate(groups):
        if not is_json_mapping(group):
            continue
        keys = group.get("keys")
        key_list = list(keys) if isinstance(keys, list) else []
        if kind.named:
            entries.append(_Entry(len(entries), group_pos, None, _compat_item(group, key_list)))
            continue
        for key_pos, key in enumerate(key_list):
            if not is_json_mapping(key):
                continue
            entries.append(_Entry(len(entries), group_pos, key_pos, _key_item(group, key)))
    return entries


def _compat_item(group: Mapping[str, JsonValue], keys: Sequence[JsonValue]) -> dict[str, JsonValue]:
    item = {field: value for field, value in group.items() if field != "keys"}
    item["api-key-entries"] = list(keys)
    first = next((key for key in keys if is_json_mapping(key)), None)
    auth_index = _auth_index(first) if first is not None else _auth_index(group)
    if auth_index:
        item["auth-index"] = auth_index
    return item


def _key_item(group: Mapping[str, JsonValue], key: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
    item: dict[str, JsonValue] = {}
    for field, value in group.items():
        if field == "base-url" or field in _SHARED_KEY_FIELDS:
            item[field] = value
    for field, value in key.items():
        if field in _AUTH_INDEX_FIELDS or value is None:
            continue
        item[field] = value
    group_name = _text(group.get("name"))
    if group_name:
        item["group"] = group_name
    auth_index = _auth_index(key)
    if auth_index:
        item["auth-index"] = auth_index
    return item


def _auth_index(node: Mapping[str, JsonValue]) -> str | None:
    for field in _AUTH_INDEX_FIELDS:
        text = _text(node.get(field))
        if text:
            return text
    return None


def _strip_auth_indexes(group: JsonValue) -> JsonValue:
    """Drop the ``auth_index`` CLIProxyAPI injects into GET replies.

    CLIProxyAPI strips it from writes as well; dropping it here keeps the body
    a plain copy of the stored config.
    """

    if not is_json_mapping(group):
        return group
    cleaned = {field: value for field, value in group.items() if field not in _AUTH_INDEX_FIELDS}
    keys = cleaned.get("keys")
    if isinstance(keys, list):
        cleaned["keys"] = [
            {field: value for field, value in key.items() if field not in _AUTH_INDEX_FIELDS}
            if is_json_mapping(key)
            else key
            for key in keys
        ]
    return cleaned


def _group(groups: list[JsonValue], entry: _Entry) -> dict[str, JsonValue]:
    current = groups[entry.group_pos]
    group = dict(current) if is_json_mapping(current) else {}
    groups[entry.group_pos] = group
    return group


def _key(group: dict[str, JsonValue], key_pos: int) -> dict[str, JsonValue]:
    keys = group.get("keys")
    key_list = list(keys) if isinstance(keys, list) else []
    current = key_list[key_pos]
    key = dict(current) if is_json_mapping(current) else {}
    key_list[key_pos] = key
    group["keys"] = key_list
    return key


def _key_count(group: Mapping[str, JsonValue]) -> int:
    keys = group.get("keys")
    return sum(1 for key in keys if is_json_mapping(key)) if isinstance(keys, list) else 0


def _set_shared_field(groups: list[JsonValue], entry: _Entry, field: str, value: JsonValue) -> None:
    """Set one shared field for exactly the credential ``entry`` names.

    An openai-compatibility group is one credential, so the group gets it. A
    single-key group gets it on the group, unless the key already overrides
    the field. In a group with several keys only this key gets the value, as
    a per-key override, so its neighbors keep the group value.
    """

    group = _group(groups, entry)
    if entry.key_pos is None:
        group[field] = value
        return
    key = _key(group, entry.key_pos)
    if key.get(field) is not None or _key_count(group) > 1:
        key[field] = value
        return
    group[field] = value


def _set_base_url(groups: list[JsonValue], entry: _Entry, base_url: str) -> None:
    """Change the endpoint of one credential.

    ``base-url`` is a group field only. A key in a group with several keys is
    moved into its own group right after the original, carrying the group's
    shared fields, so the other keys keep their endpoint and the original
    group keeps its name.
    """

    group = _group(groups, entry)
    if group.get("base-url") == base_url:
        return
    if entry.key_pos is None or _key_count(group) <= 1:
        group["base-url"] = base_url
        return
    keys = group.get("keys")
    key_list = list(keys) if isinstance(keys, list) else []
    moved = key_list.pop(entry.key_pos)
    group["keys"] = key_list
    split = {field: copy.deepcopy(value) for field, value in group.items() if field != "keys"}
    split["name"] = _unique_group_name(groups, _text(group.get("name")) or "group")
    split["base-url"] = base_url
    split["keys"] = [moved]
    groups.insert(entry.group_pos + 1, split)


def _unique_group_name(groups: Sequence[JsonValue], base: str) -> str:
    taken = {_text(group.get("name")) for group in groups if is_json_mapping(group)}
    suffix = 2
    while f"{base}-{suffix}" in taken:
        suffix += 1
    return f"{base}-{suffix}"


def _find(entries: Sequence[_Entry], index: int, account_id: str, kind: ApiKeyKind) -> _Entry:
    if 0 <= index < len(entries) and api_key_account_id(kind, entries[index].item) == account_id:
        return entries[index]
    raise DashboardConflictError(_STALE_ACCOUNT)


def _all_entries(config: _ApiKeyConfig) -> list[tuple[ApiKeyKind, _Entry]]:
    found: list[tuple[ApiKeyKind, _Entry]] = []
    for kind in API_KEY_KINDS.values():
        for entry in _entries(kind, config.families.get(kind.family, [])):
            found.append((kind, entry))
    return found


# --- public reads ----------------------------------------------------------


async def list_api_key_accounts(
    client: ClaudeSidecarClient,
    raw_files: Sequence[Mapping[str, JsonValue]],
) -> tuple[list[CliproxyApiKeyAccount], str | None]:
    """Read every supported API-key family in one config read."""

    try:
        config = await _read_config(client)
    except ClaudeSidecarError as exc:
        return [], exc.message
    accounts: list[CliproxyApiKeyAccount] = []
    for kind, entry in _all_entries(config):
        accounts.append(await _project(client, kind, entry.index, entry.item, raw_files))
    return accounts, None


@dataclass(frozen=True, slots=True)
class ApiKeyRouteRow:
    """One API-key credential the capacity router can pin, without the secret."""

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

    config = await _read_config(client)
    rows: list[ApiKeyRouteRow] = []
    for kind, entry in _all_entries(config):
        item = entry.item
        models = tuple(
            text
            for model in _configured_models(item.get("models"))
            if (text := model.alias.strip() or model.name.strip())
        )
        rows.append(
            ApiKeyRouteRow(
                kind=kind.slug,
                index=entry.index,
                name=_route_name(kind, entry),
                prefix=_text(item.get("prefix")),
                disabled=bool(item.get("disabled")) if kind.supports_disable else False,
                models=models,
                auth_index=_text(item.get("auth-index")),
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
    """Return prefixes currently stored on API-key credentials.

    ``skip`` is ``(kind, index)`` for the credential being edited, so its own
    prefix is not treated as a collision.
    """

    config = await _read_config(client)
    found: list[str] = []
    for kind, entry in _all_entries(config):
        if skip is not None and skip == (kind.slug, entry.index):
            continue
        prefix = _text(entry.item.get("prefix"))
        if prefix:
            found.append(prefix)
    return found


# --- public writes ---------------------------------------------------------


async def create_api_key_account(
    client: ClaudeSidecarClient,
    raw_files: Sequence[Mapping[str, JsonValue]],
    write: ApiKeyWrite,
) -> CliproxyApiKeyAccount:
    """Append one new group holding the new key. Existing groups are copied unchanged."""

    kind = api_key_kind(write.kind)

    def edit(_config: _ApiKeyConfig, groups: list[JsonValue]) -> tuple[list[JsonValue] | None, str]:
        groups.append(_new_group(kind, write, groups))
        created = _entries(kind, groups)[-1]
        return groups, local_auth_index(kind, created.item)

    identity = await _edit_family(client, kind, edit)
    # Find the new credential by identity, not by position: another writer may
    # append its own group between our write and this read.
    config = await _read_config(client)
    for entry in reversed(_entries(kind, config.families.get(kind.family, []))):
        if identity in {api_key_route_identity(kind, entry.item), local_auth_index(kind, entry.item)}:
            return await _project(client, kind, entry.index, entry.item, raw_files)
    raise DashboardConflictError(_STALE_ACCOUNT)


async def update_api_key_account(
    client: ClaudeSidecarClient,
    raw_files: Sequence[Mapping[str, JsonValue]],
    index: int,
    write: ApiKeyWrite,
    account_id: str,
) -> CliproxyApiKeyAccount:
    kind = api_key_kind(write.kind)

    def edit(config: _ApiKeyConfig, groups: list[JsonValue]) -> tuple[list[JsonValue] | None, str]:
        entry = _find(_entries(kind, groups), index, account_id, kind)
        if write.update_prefix and write.prefix:
            folded = write.prefix.casefold()
            for other_kind, other in _all_entries(config):
                if other_kind.slug == kind.slug and other.index == entry.index:
                    continue
                if (_text(other.item.get("prefix")) or "").casefold() == folded:
                    raise DashboardConflictError("That prefix is already used by another CLIProxyAPI account")
        _apply_edit(kind, groups, entry, write)
        identity = _identity_after_edit(kind, entry, write)
        return groups, identity

    identity = await _edit_family(client, kind, edit)
    config = await _read_config(client)
    for entry in _entries(kind, config.families.get(kind.family, [])):
        if identity in {api_key_route_identity(kind, entry.item), local_auth_index(kind, entry.item)}:
            return await _project(client, kind, entry.index, entry.item, raw_files)
    raise DashboardConflictError(_STALE_ACCOUNT)


async def set_api_key_prefix_if_empty(
    client: ClaudeSidecarClient,
    *,
    kind_slug: str,
    route_identity: str,
    prefix: str,
) -> str | None:
    """Write ``prefix`` only when the credential with ``route_identity`` has none.

    The caller holds the prefix lock and this provider's list lock. The live
    config is searched by identity, not by a cached index, so a deletion that
    shifts the list cannot receive another credential's prefix. A prefix that
    is already stored is returned unchanged. ``None`` means that identity is
    no longer configured.

    The write changes one field on one credential and copies everything else
    in the family as stored: group names, other keys, per-key overrides, and
    fields this panel does not know. In a group with several keys the prefix
    is stored on the key, so only that credential is pinned.
    """

    kind = api_key_kind(kind_slug)

    def edit(_config: _ApiKeyConfig, groups: list[JsonValue]) -> tuple[list[JsonValue] | None, str | None]:
        match = next(
            (entry for entry in _entries(kind, groups) if api_key_route_identity(kind, entry.item) == route_identity),
            None,
        )
        if match is None:
            return None, None
        existing = _text(match.item.get("prefix"))
        if existing:
            return None, existing
        _set_shared_field(groups, match, "prefix", prefix)
        return groups, prefix

    return await _edit_family(client, kind, edit)


async def delete_api_key_account(
    client: ClaudeSidecarClient,
    kind_slug: str,
    index: int,
    account_id: str,
) -> None:
    """Remove one credential: the key, its group when it was the last key, or a compat group."""

    kind = api_key_kind(kind_slug)

    def edit(_config: _ApiKeyConfig, groups: list[JsonValue]) -> tuple[list[JsonValue] | None, None]:
        entry = _find(_entries(kind, groups), index, account_id, kind)
        group = _group(groups, entry)
        if entry.key_pos is None or _key_count(group) <= 1:
            del groups[entry.group_pos]
            return groups, None
        keys = group.get("keys")
        key_list = list(keys) if isinstance(keys, list) else []
        del key_list[entry.key_pos]
        group["keys"] = key_list
        return groups, None

    await _edit_family(client, kind, edit)


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


# --- edit helpers ----------------------------------------------------------


def _new_group(kind: ApiKeyKind, write: ApiKeyWrite, groups: Sequence[JsonValue]) -> dict[str, JsonValue]:
    models = _model_payload(write.models)
    if kind.named:
        group: dict[str, JsonValue] = {
            "name": write.name or "",
            "base-url": write.base_url,
            "keys": [{"api-key": write.api_key or ""}],
            "models": models,
        }
        if write.disabled is not None:
            group["disabled"] = write.disabled
        if write.update_support_prompt_cache_key and write.support_prompt_cache_key:
            group["support-prompt-cache-key"] = True
        return group
    key: dict[str, JsonValue] = {"api-key": write.api_key or ""}
    group: dict[str, JsonValue] = {
        "name": _unique_group_name(groups, kind.slug) if groups else f"{kind.slug}-1",
        "base-url": write.base_url,
        "keys": [key],
    }
    if models:
        group["models"] = models
    return group


def _apply_edit(kind: ApiKeyKind, groups: list[JsonValue], entry: _Entry, write: ApiKeyWrite) -> None:
    """Change only the fields the form sent, on only the credential it names.

    Everything else in the family stays as CLIProxyAPI stored it.
    """

    if write.update_models:
        _set_shared_field(groups, entry, "models", _merged_model_payload(entry.item.get("models"), write.models))
    if write.update_prefix and write.prefix:
        _set_shared_field(groups, entry, "prefix", write.prefix)
    if kind.named:
        group = _group(groups, entry)
        if write.update_name:
            group["name"] = _kept_or_new_name(group, write.name or "")
        if write.update_disabled and write.disabled is not None:
            group["disabled"] = write.disabled
        if write.update_support_prompt_cache_key and write.support_prompt_cache_key is not None:
            if write.support_prompt_cache_key:
                group["support-prompt-cache-key"] = True
            else:
                group.pop("support-prompt-cache-key", None)
        if write.api_key:
            group["keys"] = _replace_first_key(group.get("keys"), write.api_key)
        group["base-url"] = write.base_url
        return
    if write.api_key and entry.key_pos is not None:
        _key(_group(groups, entry), entry.key_pos)["api-key"] = write.api_key
    _set_base_url(groups, entry, write.base_url)


def _identity_after_edit(kind: ApiKeyKind, entry: _Entry, write: ApiKeyWrite) -> str:
    item = dict(entry.item)
    item.pop("auth-index", None)
    item["base-url"] = write.base_url
    if write.api_key:
        if kind.named:
            item["api-key-entries"] = _replace_first_key(item.get("api-key-entries"), write.api_key)
        else:
            item["api-key"] = write.api_key
    return api_key_route_identity(kind, item)


def _replace_first_key(raw: JsonValue | None, api_key: str) -> list[JsonValue]:
    entries: list[JsonValue] = []
    if isinstance(raw, list):
        entries = [dict(entry) if is_json_mapping(entry) else entry for entry in raw]
    if not entries:
        return [{"api-key": api_key}]
    first = entries[0]
    if is_json_mapping(first):
        replaced = {field: value for field, value in first.items() if field not in _AUTH_INDEX_FIELDS}
        replaced["api-key"] = api_key
        entries[0] = replaced
        return entries
    return [{"api-key": api_key}, *entries[1:]]


# --- projection ------------------------------------------------------------


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
    raw_disabled = item.get("disabled")
    disabled = raw_disabled if kind.supports_disable and isinstance(raw_disabled, bool) else None
    name = _text(item.get("name")) if kind.named else None
    cache_key = item.get("support-prompt-cache-key") is True if kind.named else None
    return CliproxyApiKeyAccount(
        id=api_key_account_id(kind, item),
        kind=kind.slug,
        index=index,
        name=name or _fallback_name(kind, index),
        group=None if kind.named else _text(item.get("group")),
        base_url=_text(item.get("base-url")) or "",
        disabled=disabled,
        supports_disable=kind.supports_disable,
        has_api_key=_has_api_key(kind, item),
        key_count=_key_total(kind, item),
        models=configured,
        discovered_models=discovered,
        models_error=models_error,
        auth_index=auth_index,
        prefix=prefix,
        weight=_optional_int(item.get("weight")),
        priority=_optional_int(item.get("priority")),
        support_prompt_cache_key=cache_key,
    )


def _route_name(kind: ApiKeyKind, entry: _Entry) -> str:
    item = entry.item
    if kind.named:
        return _text(item.get("name")) or f"{kind.slug}:{entry.index}"
    group = _text(item.get("group"))
    return f"{group}#{(entry.key_pos or 0) + 1}" if group else f"{kind.slug}:{entry.index}"


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


# --- identity --------------------------------------------------------------


_STALE_ACCOUNT = "This API-key account changed before the edit was saved. Reload and try again."
_ACCOUNT_ID_KEY = b"codex-lb.cliproxy-api-key-account.v1"


def api_key_account_id(kind: ApiKeyKind, item: Mapping[str, JsonValue]) -> str:
    """Opaque token for the credential as the operator last saw it.

    Edit and delete send this token back. The write checks the credential
    currently at the requested index and rejects the request when the token
    does not match, so a stale page cannot land on a neighbor after the list
    shifts. The token mixes the public fields with a keyed digest of the
    stored API keys; the keys themselves are not in the token. The list index
    is not part of the token: moving an entry must not make it match a
    neighbor.
    """

    disabled = item.get("disabled") if kind.supports_disable and isinstance(item.get("disabled"), bool) else None
    payload: dict[str, JsonValue] = {
        "baseUrl": _text(item.get("base-url")) or "",
        "credential": _credential_digest(kind, item),
        "disabled": disabled,
        "kind": kind.slug,
        "models": [{"alias": model.alias, "name": model.name} for model in _configured_models(item.get("models"))],
        "name": (_text(item.get("name")) or "") if kind.named else "",
        "prefix": _text(item.get("prefix")) or "",
    }
    encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(encoded.encode()).hexdigest()


def api_key_route_identity(kind: ApiKeyKind, item: Mapping[str, JsonValue]) -> str:
    """Stable routing identity: CLIProxyAPI's own ``auth_index`` for the credential.

    CLIProxyAPI derives ``auth_index`` as the first 8 bytes of
    ``sha256("<kind>-api-key:<base-url>+<api-key>")``, hex encoded
    (``sdk/cliproxy/auth/types.go`` ``indexSeed``/``stableAuthIndex``). The
    value CLIProxyAPI reports is used when present. When it is absent (a
    disabled openai-compatibility group has no live credential, and older
    builds omit it) the same digest is computed here, so the identity and
    every sticky pin keyed on it do not move. Prefix, models, name, weight,
    priority, and the on/off switch are not part of it; only a new endpoint
    or a new key is a different credential. An openai-compatibility group is
    identified by its first key, which is the credential CLIProxyAPI reports
    first for the group.
    """

    reported = _text(item.get("auth-index"))
    if reported:
        return reported
    return local_auth_index(kind, item)


def local_auth_index(kind: ApiKeyKind, item: Mapping[str, JsonValue]) -> str:
    """CLIProxyAPI's ``auth_index`` for ``item``, computed from the stored key."""

    secrets = _credential_secrets(kind, item)
    api_key = secrets[0] if secrets else ""
    base_url = _text(item.get("base-url")) or ""
    seed = f"{kind.seed_kind}:{base_url}+{api_key}" if api_key else f"{kind.seed_kind}:{base_url}"
    return hashlib.sha256(seed.encode()).hexdigest()[:16]


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


# --- validation ------------------------------------------------------------


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


def _key_total(kind: ApiKeyKind, item: Mapping[str, JsonValue]) -> int:
    if not kind.named:
        return 1 if _text(item.get("api-key")) else 0
    entries = item.get("api-key-entries")
    if not isinstance(entries, list):
        return 0
    return sum(1 for entry in entries if is_json_mapping(entry) and _text(entry.get("api-key")))


def _fallback_name(kind: ApiKeyKind, index: int) -> str:
    label = {
        "openai-compatibility": "OpenAI-compatible",
        "claude": "Claude",
        "gemini": "Gemini",
        "codex": "Codex",
        "xai": "xAI",
    }.get(kind.slug, kind.slug)
    return f"{label} API key {index + 1}"


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
