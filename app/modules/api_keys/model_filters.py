"""Model set stored on one API-key limit.

A limit counts one shared budget. ``NULL`` means every model. A JSON list means
those models only, and a legacy plain model id means that one model. Callers
that still send or read a single ``model_filter`` keep working: one selected
model is that string, and any other set leaves the singular field empty.
"""

from __future__ import annotations

import json

ModelFilterIdentity = str | tuple[str, ...] | None


class ModelFilterDowngradeError(ValueError):
    """A stored model set cannot be represented as one model id."""


def normalize_model_filters(models: list[str] | None) -> list[str]:
    """Drop blanks and duplicates. Order is the order the caller selected."""
    if not models:
        return []
    seen: set[str] = set()
    normalized: list[str] = []
    for model in models:
        cleaned = model.strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        normalized.append(cleaned)
    return normalized


def resolve_model_filters(*, model_filter: str | None, model_filters: list[str] | None) -> list[str]:
    """The list to store. An explicit list wins, including an empty one."""
    if model_filters is not None:
        return normalize_model_filters(model_filters)
    if model_filter is None:
        return []
    return normalize_model_filters([model_filter])


def encode_model_filters(models: list[str] | None) -> str | None:
    """JSON list for the column. ``None`` means the limit applies to every model."""
    normalized = normalize_model_filters(models)
    if not normalized:
        return None
    return json.dumps(normalized, separators=(",", ":"), ensure_ascii=False)


def decode_model_filters(stored: str | None) -> list[str]:
    """Models a stored value names. An empty list means every model.

    A plain model id is kept verbatim so a row written before the list migration
    still matches only that model.
    """
    if stored is None:
        return []
    if not stored:
        return [stored]
    text = stored.strip()
    if text.startswith("["):
        try:
            parsed = json.loads(stored)
        except json.JSONDecodeError:
            return [stored]
        if isinstance(parsed, list) and all(isinstance(item, str) for item in parsed):
            return list(parsed)
    return [stored]


def stored_model_identity(stored: str | None) -> ModelFilterIdentity:
    """Identity of a stored filter. Order does not make a different rule."""
    return model_filter_identity(decode_model_filters(stored))


def model_filter_identity(models: list[str]) -> ModelFilterIdentity:
    if not models:
        return None
    if len(models) == 1:
        return models[0]
    return tuple(sorted(models))


def singular_model_filter(models: list[str]) -> str | None:
    """The legacy single-model field. Only a one-model rule has one."""
    if len(models) == 1:
        return models[0]
    return None


def limit_matches_request_model(stored: str | None, request_model: str | None) -> bool:
    """Whether a request on ``request_model`` draws on this limit's budget."""
    models = decode_model_filters(stored)
    if not models:
        return True
    if request_model is None:
        return False
    return request_model in models


def model_filter_scope_suffix(models: list[str]) -> str:
    if not models:
        return ""
    if len(models) == 1:
        return f" for model {models[0]}"
    return " for models " + ", ".join(models)


def model_filter_quota_token(models: list[str]) -> str | None:
    """Stable scope token. One model stays the bare id the old quota key used.

    Several models sort, so selecting the same set in another order keeps the
    same quota key.
    """
    if not models:
        return None
    if len(models) == 1:
        return models[0]
    return ",".join(sorted(models))


def upgrade_stored_model_filter(stored: str | None) -> str | None:
    """Wrap one legacy model id as a one-item JSON list. ``NULL`` stays ``NULL``.

    The column is an unrestricted string, so a value that looks like JSON is
    still one model id. ``[]`` must not become every model, and
    ``["model-alpha"]`` must not start matching ``model-alpha``. Wrapping the
    original text keeps the rule on the same id it matched before.
    """
    if stored is None:
        return None
    return json.dumps([stored], separators=(",", ":"), ensure_ascii=False)


def downgrade_stored_model_filter(stored: str | None) -> str | None:
    """Restore a single model id. A multi-model rule cannot be downgraded."""
    if stored is None:
        return None
    text = stored.strip()
    if not text.startswith("["):
        return stored
    try:
        parsed = json.loads(stored)
    except json.JSONDecodeError:
        return stored
    if not isinstance(parsed, list) or not all(isinstance(item, str) for item in parsed):
        return stored
    if len(parsed) > 1:
        joined = ", ".join(parsed)
        raise ModelFilterDowngradeError(
            "cannot downgrade api_key_limits.model_filter while a rule lists multiple models: " + joined
        )
    if len(parsed) == 1:
        return parsed[0]
    return None
