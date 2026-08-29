"""Deterministic, abstaining resolution of an incoming model id to a catalog id.

This module is pure: it takes an incoming id, the operator's configured routing
prefixes and explicit aliases, and one or more catalog snapshots, and returns the
catalog entry that unambiguously corresponds to the id -- or nothing.

It exists because the substring-glob table it replaces for these paths
(``DEFAULT_MODEL_ALIASES``) matched on stems. ``*claude-opus-4*`` matched
``anthropic/claude-opus-4.5`` and priced it at Opus 4.0's rate, 3x the real one;
``*llama-3.1-8b*`` matched a third-party finetune priced 8x the base model. A
stem match is not evidence of identity, so no step here matches on one.

Resolution order, first hit wins:

``alias``
    An operator's explicit ``{alias: real_model}`` entry. The operator said what
    the id means, so nothing may override it.
``prefix``
    An operator-configured routing prefix is stripped when that prefix's ``strip``
    flag is set, and the remainder re-enters resolution. This is what makes a
    CLIProxyAPI id such as ``cc/claude-fable-5`` resolve to the Anthropic catalog
    entry for ``claude-fable-5`` rather than to whatever happens to contain the
    substring ``claude``.
``exact``
    Case-folded exact id match inside a catalog.
``normalized``
    Exact match after folding ``.`` and ``_`` to ``-``, so ``claude-opus-4.5`` and
    ``claude-opus-4-5`` reach the same entry. Only a unique match counts.
``vendor-qualified``
    A bare name matched against catalog ids' trailing path segment
    (``claude-opus-5`` -> ``anthropic/claude-opus-5``). Only a unique match counts;
    ``qwen3.8-27b`` listed by two vendors at different prices abstains.

Variant suffixes (``:free``, ``:batch``) are never dropped to reach a base entry:
those variants are billed at different rates, so inheriting the base price is a
wrong number rather than a missing one. A suffixed id resolves only against a
catalog that lists that exact suffixed id.

Every step that could produce more than one candidate abstains instead of
choosing. Abstention is not conservatism here: the collisions measured in the
live catalogs differ by up to 2.8x, so a guess is wrong most of the time it
matters.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum

from app.core.usage.pricing import ModelPrice
from app.modules.proxy.sidecar_routing import prefix_variants

# ``.`` and ``_`` are pure spelling variation in every catalog observed; folding
# them introduced zero within-catalog collisions across 577 live ids.
_PUNCTUATION_RE = re.compile(r"[._]")

# Suffixes that denote a separately priced variant of another id.
VARIANT_SUFFIX_SEPARATOR = ":"


class ResolutionOutcome(str, Enum):
    RESOLVED = "resolved"
    UNRESOLVED = "unresolved"
    AMBIGUOUS = "ambiguous"
    NOT_TOKEN_PRICED = "not_token_priced"
    PRICE_UNPARSEABLE = "price_unparseable"


class UnpricedReason(str, Enum):
    """Why a listed catalog entry carries no ``ModelPrice``.

    These are different facts and must not share one representation.
    ``NO_TOKEN_RATE`` is a settled answer: the catalog listed the model and
    published no per-token rate for it, so there is nothing to find.
    ``UNPARSEABLE`` means the catalog did publish rate fields this build could
    not read, which is a parse failure rather than an answer. The last
    successfully parsed value must survive it, and the lookup must be retried.
    """

    NO_TOKEN_RATE = "no_token_rate"
    UNPARSEABLE = "unparseable"


@dataclass(frozen=True, slots=True)
class CatalogEntry:
    """One catalog model id and the rates that catalog published for it.

    ``price`` is ``None`` for a model the catalog lists but does not price per
    token (per-request image models, per-minute audio, routers with no fixed
    upstream). That is a real listing, not a lookup failure, and must not be
    retried as though the catalog were unreachable.

    ``unpriced_reason`` separates that settled answer from an entry whose
    published rate fields could not be parsed. It defaults to ``NO_TOKEN_RATE``
    so a source that cannot tell the two apart keeps the reading it always had;
    a parser that can tell says so explicitly.
    """

    model_id: str
    price: ModelPrice | None
    unpriced_reason: UnpricedReason = UnpricedReason.NO_TOKEN_RATE


@dataclass(frozen=True, slots=True)
class Catalog:
    """A single source's model listing, indexed for the steps above."""

    source: str
    entries: Mapping[str, CatalogEntry]
    _normalized: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    _bare: Mapping[str, tuple[str, ...]] = field(default_factory=dict)

    @classmethod
    def from_entries(cls, source: str, entries: Iterable[CatalogEntry]) -> "Catalog":
        indexed: dict[str, CatalogEntry] = {}
        for entry in entries:
            key = entry.model_id.strip().lower()
            if not key:
                continue
            indexed[key] = entry
        normalized: dict[str, list[str]] = {}
        bare: dict[str, list[str]] = {}
        for key in indexed:
            normalized.setdefault(normalize_model_key(key), []).append(key)
            bare.setdefault(normalize_model_key(_bare_name(key)), []).append(key)
        return cls(
            source=source,
            entries=indexed,
            _normalized={key: tuple(value) for key, value in normalized.items()},
            _bare={key: tuple(value) for key, value in bare.items()},
        )

    def exact(self, model_key: str) -> CatalogEntry | None:
        return self.entries.get(model_key)

    def normalized_candidates(self, model_key: str) -> tuple[str, ...]:
        return self._normalized.get(normalize_model_key(model_key), ())

    def bare_candidates(self, model_key: str) -> tuple[str, ...]:
        return self._bare.get(normalize_model_key(model_key), ())


@dataclass(frozen=True, slots=True)
class Resolution:
    outcome: ResolutionOutcome
    catalog_model: str | None = None
    catalog_source: str | None = None
    price: ModelPrice | None = None
    step: str | None = None
    detail: str | None = None


def normalize_model_key(value: str) -> str:
    """Fold spelling-only punctuation so ``x-4.5`` and ``x-4_5`` share a key."""

    return _PUNCTUATION_RE.sub("-", value.strip().lower())


def _bare_name(model_key: str) -> str:
    """Trailing path segment of a vendor-qualified id."""

    return model_key.rsplit("/", 1)[-1]


def _has_variant_suffix(model_key: str) -> bool:
    return VARIANT_SUFFIX_SEPARATOR in _bare_name(model_key)


def resolve_model_price(
    incoming_model: str,
    *,
    catalogs: Sequence[Catalog],
    aliases: Mapping[str, str] | None = None,
    prefixes: Sequence[tuple[str, bool]] = (),
) -> Resolution:
    """Resolve ``incoming_model`` against ``catalogs`` in precedence order.

    ``catalogs`` must already be ordered by authority: the serving provider's own
    catalog first, then the broad pricing reference. ``prefixes`` are the
    operator's configured ``(prefix, strip)`` routing entries for the serving
    integration. ``aliases`` is the operator's explicit alias map.

    Never raises. A caller that cannot distinguish outcomes still gets a usable
    ``Resolution`` describing why no price was produced.
    """

    normalized_input = (incoming_model or "").strip()
    if not normalized_input:
        return Resolution(outcome=ResolutionOutcome.UNRESOLVED, detail="empty model id")

    # ``seen`` guards the alias/prefix rewrite loop: an alias map that points an
    # id back at itself, or a prefix whose stripped remainder is aliased back to
    # the original, would otherwise spin.
    seen: set[str] = set()
    candidate = normalized_input.lower()
    step_prefix = ""

    while candidate not in seen:
        seen.add(candidate)

        aliased = _resolve_alias(candidate, aliases)
        if aliased is not None and aliased not in seen:
            step_prefix = "alias+" if not step_prefix else step_prefix
            candidate = aliased
            continue

        resolution = _resolve_against_catalogs(candidate, catalogs)
        if resolution.outcome is not ResolutionOutcome.UNRESOLVED:
            return _with_step_prefix(resolution, step_prefix)

        stripped = _strip_configured_prefix(candidate, prefixes)
        if stripped is not None and stripped not in seen:
            step_prefix = f"{step_prefix}prefix+"
            candidate = stripped
            continue

        break

    return Resolution(
        outcome=ResolutionOutcome.UNRESOLVED,
        detail=f"no catalog entry for {normalized_input!r}",
    )


def _with_step_prefix(resolution: Resolution, step_prefix: str) -> Resolution:
    if not step_prefix or resolution.step is None:
        return resolution
    return Resolution(
        outcome=resolution.outcome,
        catalog_model=resolution.catalog_model,
        catalog_source=resolution.catalog_source,
        price=resolution.price,
        step=f"{step_prefix}{resolution.step}",
        detail=resolution.detail,
    )


def _resolve_alias(model_key: str, aliases: Mapping[str, str] | None) -> str | None:
    """Operator's explicit alias target for ``model_key``, case-folded.

    Exact key match only. An alias map is a statement about specific ids; pattern
    matching it would reintroduce the stem-matching defect this module exists to
    remove.
    """

    if not aliases:
        return None
    for alias, target in aliases.items():
        if alias.strip().lower() != model_key:
            continue
        resolved = target.strip().lower()
        return resolved or None
    return None


def _strip_configured_prefix(model_key: str, prefixes: Sequence[tuple[str, bool]]) -> str | None:
    """Remainder after removing the longest configured strip-enabled prefix.

    Only prefixes the operator marked ``strip`` are removed, and only the longest
    match, mirroring ``resolve_sidecar_route``. A prefix the operator forwards
    verbatim is part of the upstream's own id, so removing it here would ask the
    catalog about a model that does not exist.
    """

    best = ""
    for prefix, strip in prefixes:
        if not strip:
            continue
        for variant in prefix_variants(prefix):
            if variant and model_key.startswith(variant) and len(variant) > len(best):
                best = variant
    if not best:
        return None
    remainder = model_key[len(best) :].strip()
    return remainder or None


def _resolve_against_catalogs(model_key: str, catalogs: Sequence[Catalog]) -> Resolution:
    """Run the exact/normalized/vendor-qualified steps over ``catalogs`` in order.

    Each step is tried across every catalog before the next, weaker step begins,
    so a precise match in the fallback catalog beats a fuzzy match in the first.
    An ambiguity found by a step ends resolution: a weaker step cannot disambiguate
    what a stronger one could not.
    """

    for catalog in catalogs:
        entry = catalog.exact(model_key)
        if entry is not None:
            return _entry_resolution(entry, catalog, step="exact")

    for catalog in catalogs:
        resolution = _unique_candidate(model_key, catalog, catalog.normalized_candidates(model_key), step="normalized")
        if resolution is not None:
            return resolution

    # A variant id (``...:batch``) never falls back to its base entry: the base
    # rate is a different, wrong price rather than a missing one.
    if _has_variant_suffix(model_key):
        return Resolution(
            outcome=ResolutionOutcome.UNRESOLVED,
            detail=f"no catalog entry for variant {model_key!r}; base-model price would be a different rate",
        )

    for catalog in catalogs:
        resolution = _unique_candidate(
            model_key,
            catalog,
            catalog.bare_candidates(model_key),
            step="vendor-qualified",
        )
        if resolution is not None:
            return resolution

    return Resolution(outcome=ResolutionOutcome.UNRESOLVED)


def _unique_candidate(
    model_key: str,
    catalog: Catalog,
    candidates: Sequence[str],
    *,
    step: str,
) -> Resolution | None:
    """One resolution from ``candidates``, or an abstention, or ``None`` to continue.

    ``None`` means this catalog had nothing to say, so the caller should try the
    next one. A returned ``AMBIGUOUS`` means this catalog had several equally
    plausible answers, which no later step can improve on.
    """

    if not candidates:
        return None
    # A base id and its own variants are not competing answers to an unsuffixed
    # query: the caller asked for the base rate, so prefer the unsuffixed entry.
    unsuffixed = [candidate for candidate in candidates if not _has_variant_suffix(candidate)]
    if not _has_variant_suffix(model_key) and unsuffixed:
        candidates = unsuffixed
    if len(candidates) > 1:
        return Resolution(
            outcome=ResolutionOutcome.AMBIGUOUS,
            catalog_source=catalog.source,
            step=step,
            detail="matches " + ", ".join(sorted(candidates)),
        )
    entry = catalog.exact(candidates[0])
    if entry is None:
        return None
    return _entry_resolution(entry, catalog, step=step)


def _entry_resolution(entry: CatalogEntry, catalog: Catalog, *, step: str) -> Resolution:
    if entry.price is None:
        if entry.unpriced_reason is UnpricedReason.UNPARSEABLE:
            # The source listed the model and published rate fields this build
            # could not read. Saying "not token priced" here would settle a
            # question the catalog actually answered, clear a good rate, and set
            # no retry, so one upstream schema change would erase every rate.
            return Resolution(
                outcome=ResolutionOutcome.PRICE_UNPARSEABLE,
                catalog_model=entry.model_id,
                catalog_source=catalog.source,
                step=step,
                detail="catalog published a price in a shape this build could not parse",
            )
        return Resolution(
            outcome=ResolutionOutcome.NOT_TOKEN_PRICED,
            catalog_model=entry.model_id,
            catalog_source=catalog.source,
            step=step,
            detail="catalog lists the model without a per-token price",
        )
    return Resolution(
        outcome=ResolutionOutcome.RESOLVED,
        catalog_model=entry.model_id,
        catalog_source=catalog.source,
        price=entry.price,
        step=step,
    )
