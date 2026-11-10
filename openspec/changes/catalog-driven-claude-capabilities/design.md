## Context

See `proposal.md` for motivation and `specs/upstream-metadata/spec.md` for the behavior contract.

`pricing_catalog.py` already fetches models.dev hourly, with a 16 MiB bound and last-good pricing cache. Its parser currently keeps only OpenAI prices. Claude sidecar `/v1/models` rows are built separately from operator-managed model sources. Their default text/image decision comes from provider metadata or the fixed Claude context table, not `model_sources/catalog.py` or `_v1_supports_vision`.

## Goals / Non-Goals

**Goals:** share the existing fetch and persistence lifecycle; keep pure in-memory request lookups; preserve exact model identity and all fixed bounds.

**Non-Goals:** changing price resolution, cache-write billing, model-source settings, other provider policies, or live infrastructure.

## Decisions

1. Return a typed metadata refresh containing the existing price map plus a separate Claude capability map. Parse capabilities from the same decoded models.dev payload. This avoids a second request and keeps fetches free of global installation side effects. A runtime refresh succeeds when either map contains valid data; a capability-only refresh returns an empty price update so installation preserves last-good prices.
2. Store optional `model_capabilities` in the version-1 pricing snapshot format. Legacy caches remain valid. The current bundled snapshot contains no Claude metadata, so a cold offline start retains the fixed-table and unknown-id behavior. Merge valid fields and preserve absent or malformed fields across partial updates, like last-good pricing. The existing snapshot generator retains the same metadata from its models.dev payload, so future generated bundles provide the same offline fallback without another fetch.
3. Use `strip_known_sidecar_prefix` once for capability lookup, not the broader pricing alias resolver. Exact catalog keys remain distinct, including dotted, dated, and suffixed ids.
4. Public catalog modalities win for known Claude rows; provider metadata and the existing fixed-model vision heuristic remain the fallback. Use the same resolved modalities to generate vision flags and input modalities. Do not infer vision from newly catalog-derived context limits.
5. Keep fixed output rows first. Only an id without a fixed row and with both positive integer limits gets derived bounds. Reuse the existing mutation algorithm, floor, keep-warm exemption, and context guard unchanged.

## Risks / Trade-offs

- [Remote metadata is missing or malformed] → Ignore invalid fields and retain last-good values; otherwise retain prior fixed/unknown behavior.
- [A catalog refresh changes an existing fixed model's limits] → Fixed bounds remain authoritative for dispatch.
- [Metadata is stale during an outage] → Retain the last-good snapshot, matching pricing's existing availability policy; do not guess another model's row.
- [A catalog entry has limits but no modalities] → It can gain bounds but cannot gain image support from those limits alone.

## Migration Plan

No database migration. The next normal metadata refresh populates capabilities and persists them in the existing cache. Rollback ignores the additive cache field. Deployment and live verification remain with the supervising session.
