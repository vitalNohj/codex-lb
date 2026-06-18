## Context

Three sidecar integrations exist today, each implemented independently:

- **CLIProxyAPI** (code name `claude_sidecar`): longest-prefix match (`app/modules/proxy/sidecar_prefix.py`), strips a matched prefix only when it ends in `-`/`_`, plus built-in always-on alias prefixes `cp-`/`cp_`. Has a management key.
- **OpenRouter**: first-prefix match (`openrouter_sidecar_dispatch.py`), same alias-only strip rule. No management key, no full-model routing.
- **OmniRoute**: exact case-insensitive selected-model match only (`omniroute_sidecar_dispatch.py`), never strips. No prefix routing.

Routing precedence is hardcoded in `app/modules/proxy/api.py` (`v1_chat_completions`, ~lines 2122-2180) as Claude → OpenRouter → OmniRoute, with a separate Responses dispatch (~lines 491-519). All settings live on the single `DashboardSettings` table (`app/db/models.py:593-743`); prefixes are stored as JSON string arrays, OmniRoute's selected models as a JSON string array. Pydantic models live in `app/modules/settings/schemas.py:162-269`.

The Settings UI has three near-duplicate components (`{claude,openrouter,omniroute}-sidecar-settings.tsx`, ~230-270 lines each) and two near-identical model browsers, sharing only generic UI primitives. There is no shared sidecar component.

Constraints:
- OpenSpec-first: routing, schema, API, and dashboard-visible behavior are gated.
- Single Alembic head; new revision must sit on the current head with up/down and historical backfill.
- Secrets are encrypted via `TokenEncryptor`; the CLIProxyAPI management key is stored plaintext-in (app encrypts) because the sidecar hashes it.
- The Cursor↔OpenAI compatibility layer must not diverge from upstream; per-provider dispatch behavior (payload shaping, usage capture, reservations) must be preserved — only matching/wire-model selection is being unified.

## Goals / Non-Goals

**Goals:**
- One provider-agnostic routing/filter resolver, used by both chat-completions and Responses paths, that decides *which* integration owns a model and *what wire model* to send.
- Uniform field set across integrations: base URL, API key, prefixes (`{prefix, strip}`), full-model list, discovered-models browser, timeouts, cache TTL. Management key remains CLIProxyAPI-only.
- Full model name exact match beats prefix match **globally**; full-name matches are sent as-is and never stripped.
- Global uniqueness of prefixes and full-model names across all integrations, validated client-side and server-side.
- A single shared `<SidecarIntegrationCard>` compound component replacing the three duplicated Settings components and two browsers.
- Preserve current effective routing behavior via migration backfill (no surprise re-routing on upgrade).

**Non-Goals:**
- Changing per-provider dispatch internals (payload shaping, usage extraction, reservation/settlement, cost capture, quota/usage polling).
- Changing the integration enable/disable model or the synthetic-account/Accounts-tab surfaces beyond what field changes require.
- Adding management keys to OpenRouter/OmniRoute.
- Introducing a new capability folder; this modifies existing capabilities only.

## Decisions

### D1 — Single resolver returning a routing decision
Add `app/modules/proxy/sidecar_routing.py` exposing a pure function that takes the effective model and the set of enabled integration configs and returns a decision: `(provider, wire_model)` or `None`. Algorithm:
1. **Full-name pass**: case-insensitive exact compare of the effective model against every integration's full-model list. First hit (in Claude → OpenRouter → OmniRoute fallback order) wins; `wire_model = effective_model` as-is (no strip).
2. **Prefix pass**: if no full-name hit, scan every integration's prefix rows. Longest matching prefix wins (across all integrations); `wire_model` is the effective model with the prefix removed iff that row's `strip` is true, else as-is.
3. Otherwise `None` → native Codex path.

`api.py` calls the resolver once and dispatches to the matching provider's existing `proxy_chat_to_*` (or Responses equivalent), passing the resolver-provided `wire_model` as `effective_model`.

*Rationale:* Centralizes precedence and strip semantics; removes three divergent matchers. Longest-prefix is chosen as the universal rule (superset of OpenRouter's first-match; deterministic). The Claude→OpenRouter→OmniRoute order is retained only as a tiebreaker that uniqueness makes unreachable.

*Alternatives considered:* Keep per-integration matchers and only add a thin precedence wrapper — rejected; it leaves the strip/full-name divergence and duplicated logic. First-match prefix — rejected; non-deterministic under overlap and weaker than longest-match.

### D2 — Prefixes as `{prefix, strip}` objects; built-in aliases become seeded defaults
Store prefixes as JSON arrays of objects. Remove the hardcoded `_BUILTIN_SIDECAR_ALIAS_PREFIXES` (`cp-`/`cp_`) in `sidecar_prefix.py`; instead seed them as default editable prefix rows (`strip: true`) for CLIProxyAPI in the migration's backfill and as schema defaults.

*Rationale:* Makes strip explicit and per-prefix as requested; makes the `cp-`/`cp_` behavior transparent and removable. *Alternative:* keep aliases implicit — rejected (opaque, inconsistent with the "everything is a visible prefix row" model).

### D3 — Single full-model list per integration (generalize OmniRoute selected_models)
One per-integration list of exact model IDs. Clicking a discovered model and typing a full name both append to it; it renders outside the discovered browser. OmniRoute's `selected_models_json` is reused/renamed to the full-models column; CLIProxyAPI and OpenRouter gain the same column.

*Rationale:* The user confirmed selected-models and full-name-add are the same list. *Alternative:* two distinct lists — rejected per user.

### D4 — Cross-integration uniqueness validation (client + server)
A normalized key space: prefixes normalized to lowercase, full-model names compared case-insensitively. A value (prefix OR full-model name) may appear in at most one integration. Exception by construction: a prefix string and a full-model string may coincide textually across integrations because they live in different namespaces and full-name wins at routing time; this is allowed and is the documented `minimax/` vs `minimax/minimax-m3` case.

Server: a validator on the settings update path computes the union across the post-update state of all three integrations and rejects on collision with a structured error (`code`, conflicting `value`, `kind` = prefix|full_model, `owning_integration`). Client: the shared component blocks the add and renders red inline text naming the owning integration.

*Rationale:* UI-only validation can be bypassed (direct API/import); server is authoritative. *Alternative:* server-only — rejected; poor UX, the user explicitly asked for inline red-text rejection.

### D5 — Shared `<SidecarIntegrationCard>` compound component
Per the workspace Vercel composition skill: a context provider injects `state`/`actions`/`meta` per integration; subcomponents (`Header`, `EnableToggle`, `Callout`, `BaseUrl`, `ApiKey`, `ManagementKey`, `Prefixes`, `FullModels`, `DiscoveredModels`, `Timeouts`, `Actions`) consume context. Integration-specific variants compose only the pieces they need (OpenRouter/OmniRoute omit `ManagementKey`). The discovered-models browser is one shared component (replaces both existing browsers).

*Rationale:* Eliminates ~760 lines of duplication; follows the mandated composition pattern. *Alternative:* boolean-prop mega-component — rejected by the composition guidelines.

## Risks / Trade-offs

- [Strip semantics change from auto-alias to per-prefix flag could silently re-route/re-shape models on upgrade] → Migration backfills `strip: true` for existing prefixes ending in `-`/`_` and `strip: false` otherwise, and seeds `cp-`/`cp_` (strip true) for CLIProxyAPI, reproducing today's effective behavior. Add tests asserting parity for representative models.
- [OmniRoute now supports prefixes; an operator could add a prefix that captures more than intended] → Prefix routing is opt-in (empty by default for OmniRoute via backfill); full-name list (migrated from selected_models) keeps existing OmniRoute routes intact and full-name still wins.
- [Cross-integration uniqueness rejection could block a previously-savable config] → Pre-existing data cannot contain cross-integration duplicates for the same kind today (each integration validated independently), but prefix-vs-prefix duplicates across integrations were previously allowed; the migration/validator must detect and surface such legacy collisions rather than crash. Mitigation: validator runs on read for diagnostics and the migration logs (does not silently drop) any detected collision.
- [Responses path divergence] → Route Responses through the same resolver; add a Responses-path test mirroring the chat-completions precedence test.
- [Single large change spanning schema + routing + UI] → Sequence tasks so backend resolver + migration land with parity tests before UI swap; keep per-provider dispatch untouched to bound blast radius.

## Migration Plan

1. New Alembic revision on the current single head.
2. **Upgrade**: transform each `*_model_prefixes_json` array-of-strings → array-of-`{prefix, strip}` (strip = ends-with `-`/`_`); add `claude_sidecar_full_models_json` and `openrouter_sidecar_full_models_json` (default `[]`); ensure OmniRoute full-models column holds the prior `selected_models` values; seed CLIProxyAPI default prefix rows including `cp-`/`cp_` (strip true) where absent.
3. **Downgrade**: collapse `{prefix, strip}` back to string arrays (drop strip), drop the added full-model columns, restore OmniRoute selected_models naming.
4. Deploy backend (resolver + schema) first; behavior is preserved by backfill. Then deploy frontend (shared component). Service restart only when the operator confirms it is safe (shared systemd instance).
5. Rollback: revert frontend, then `alembic downgrade -1`.

## Open Questions

- None blocking. The `cp-`/`cp_` seeding and the single full-model-list decisions were confirmed with the user; remaining details (exact column rename vs add-new for OmniRoute) are an implementation choice settled in tasks, defaulting to reusing `omniroute_sidecar_selected_models_json` as the OmniRoute full-models store to minimize migration churn.
