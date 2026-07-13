## Context

CLIProxyAPI (wired in codex-lb as `claude_sidecar`) already holds multiple upstream credentials in one process. codex-lb uses one `base_url` + API key for chat and one Management API key for auth-files / strategy / pause / usage-queue.

**Transport** is mostly provider-agnostic (prefix/full-model → `proxy_chat_to_sidecar`). **Observation/control is Claude-scoped today:**

| Path | Current trap if filters are widened alone |
|------|-------------------------------------------|
| `quota.py::_is_claude_entry` / `service._routing_accounts` | Drop non-Claude |
| `quota_poller._attach_oauth_usage` | Calls Anthropic OAuth for **every** `auth_index` |
| `usage_estimates.build_claude_usage_estimates` | Invents 5h + 7d Claude plan math for every account |
| `ClaudeAuthCard` / list rows | Always render 5h + weekly bars |
| `ClaudeSidecarRoutingAccount` | No `provider` field |
| `SidecarAuthAccount` | Has `provider`, but no `quota_windows` / `supports_manual_plan` |
| `dashboard/api.py` / `/v1/models` | Hard-label / `owned_by: anthropic` for all CLIProxyAPI models |
| `sidecar_summary` parent | Aggregates all auth estimates into one Claude-shaped parent usage |

This design locks adapter-first delivery so implementation cannot ship Option-1 “widen filter only.”

## Goals / Non-Goals

**Goals:**

- Surface all CLIProxyAPI auth files with usable `name` in routing, pause/priority, and per-auth Dashboard cards.
- One global strategy + priority namespace; UI labels provider on every row.
- Correct observation via adapters; concrete API fields for windows/manual plans.
- Grok routing via existing CLIProxyAPI integration; honest catalog labels.
- Request Logs Account stays `CLIProxyAPI: <account>`.

**Non-Goals:**

- `claude_sidecar` → `cliproxy` rename.
- Second Settings tab for same CLIProxyAPI URL.
- Provider qualifiers in Request Logs Account cells.
- Per-upstream effort overrides (shared override remains).
- Owning CLIProxyAPI login/process.
- Changing OpenRouter / OmniRoute / Ollama / native Codex LB.
- Claiming per-model-family credential pick without Phase-0 proof.

## Decisions

### D1 — Adapter registry first (Option 2)

**Choice:** Add an internal provider-adapter registry before removing Claude-only filters. Adapters own observation only; pause/priority/strategy stay provider-agnostic Management API passthrough.

**Normalized provider keys (codex-lb):**

| Upstream signals (examples) | Normalized key | Human label |
|-----------------------------|----------------|-------------|
| `provider`/`type` ≈ `claude`, `account_type` ≈ `anthropic` | `claude` | `Claude` |
| `provider`/`type` ≈ `xai` / `grok` (exact strings from spike) | `xai` | `Grok` |
| anything else with usable name | `unknown` | `CLIProxyAPI` |

Spike MAY refine alias map; specs use normalized keys above.

### D8 — Observation API contract (normative shape)

Every Dashboard/routing auth row produced for CLIProxyAPI MUST include:

| Field | Type | Meaning |
|-------|------|---------|
| `provider` | string | Normalized key (`claude` / `xai` / `unknown` / …) |
| `quota_windows` | ordered list of `"five_hour"` \| `"weekly"` | Windows the UI MAY render bars for |
| `supports_manual_plan` | bool | Whether Accounts estimation inputs apply |

**Claude adapter:** `quota_windows=["five_hour","weekly"]`, live Anthropic OAuth allowed, `supports_manual_plan=true` (existing).  
**Grok/xAI adapter (pre-spike default):** `quota_windows=[]` or `["weekly"]` only after spike proves weekly; never invent `five_hour` without proof; `supports_manual_plan=true`.  
**Default/unknown:** `quota_windows=[]`, `supports_manual_plan=true`, no Anthropic OAuth.

Frontend MUST key bar visibility off `quota_windows`, not off provider name string matching alone.

### D2 — Global credential pool (locked)

One `round_robin` / `fill_first` strategy and one priority/pause list across all auth files. Routing rows MUST show provider label + account identity.

**Upstream family selection is spike-gated:** design does **not** assert that CLIProxyAPI always picks credentials by model family. Phase 0 MUST verify with a Grok request under interleaved priorities. If CLIProxyAPI can burn the wrong-provider credential, capture that in `context.md` and add an operator warning in Settings routing help text; do not invent a second strategy API in codex-lb.

**Priority sort direction is spike-gated:** UI today says “higher number = preferred”; some docs claim lower-is-preferred for CLIProxyAPI. Phase 0 MUST record which CLIProxyAPI actually uses; operator banding docs MUST match that.

### D3 — Auth ingestion

1. Usable `name` = non-empty trimmed auth-file `name` string. Entries without usable `name` are skipped (cannot pause/priority-target them).
2. Ingest all usable names; classify via D1 normalization.
3. Unify today’s inconsistent filters (`_is_claude_entry` vs `_routing_accounts` missing `account_type==anthropic`) by deleting Claude-only gates after adapters exist.

**Atomicity:** land adapter registry + poller OAuth gate + estimate window respect in the same implementation slice as filter removal (or adapters first in the same PR). Never deploy widened ingestion alone.

### D4 — Auth plans (array, additive)

**Choice:** Keep `claude_sidecar_auth_plans` as a JSON **array** of plan rows (current shape). Add optional `provider` on each row for disambiguation.

Matching: existing identity fields (`auth_index` / `email` / `source`) plus `provider` when present. Claude rows without `provider` continue to match Claude auths (backward compatible).

Plan types:

- Claude: existing `pro|max5|max20|custom` with existing budget rules.
- Non-Claude (Grok/unknown): `custom` only in v1. Required budgets follow declared windows: if only `weekly` is declared (or manual-only with weekly target), require secondary/weekly budget; do not require a fake five-hour budget when `five_hour` is absent from `quota_windows`.

Estimation UI MUST list non-Claude auths and MUST NOT default new Grok rows to Claude `pro` presets.

### D4b — Parent synthetic aggregate

When `sidecar_auths` contains more than one distinct normalized `provider`, the synthetic parent (`account_id=claude-sidecar`) MUST NOT expose a blended 5h/weekly `usage` aggregate as if it were one Claude quota. Prefer `usage=null` on the parent and let per-auth cards carry truth. Single-provider Claude-only deployments keep today’s aggregate behavior.

Dashboard `cliproxy` filter continues to key off parent `provider="claude"` / synthetic CLIProxyAPI account — no new filter key required.

### D5 — Request Logs Account + correlation

Account text unchanged: `CLIProxyAPI: <label>` / `CLIProxyAPI`.

**Correlation improvement:** when multiple usage events fall in the 30s window, prefer an event whose `provider` matches the request’s known upstream provider if available (from model/routing/dispatch metadata or usage event fields); otherwise keep existing nearest-timestamp behavior. Account text still ignores provider.

### D6 — Routing + catalog

- Internal sidecar resolver id stays `"claude"` (= CLIProxyAPI integration). Do **not** add a parallel `"xai"` sidecar provider key in `sidecar_routing.py`.
- Grok models route only when prefixes/full-models match; bare `grok-*` without config MUST NOT force CLIProxyAPI.
- Dashboard discovered-model loop MUST NOT prefix non-Claude ids with `Claude:`.
- `/v1/models` entries for non-Claude CLIProxyAPI models MUST NOT set `owned_by: "anthropic"`. Prefer `owned_by: "cliproxyapi"` (or provider-accurate value) and display label `CLIProxyAPI: <id>` unless Claude-classified.
- Reference cost: MUST NOT apply Anthropic price rows to non-Claude model ids; unknown → `NULL` (not zero). Optional Grok price table is Phase 2.

### D7 — Effort override

One shared `claude_sidecar_default_reasoning_effort` for all CLIProxyAPI auths remains. Grok may ignore or differently interpret OpenAI `reasoning_effort`; document as known limitation, not a silent Claude-only feature claim in UI copy.

### D9 — Phased delivery

| Phase | Scope | Gate |
|-------|-------|------|
| 0 Spike | xAI login, auth-file shape, usage windows, priority direction, family selection probe, model ids | Blocks finalizing Grok `quota_windows` + operator priority docs |
| 1 Auth surface | Adapters + poller gate + estimates + schemas + widen filters + UI bars/routing/estimation + correlation prefer-provider | Atomic; `codex-lb` restart with operator OK |
| 2 Grok routing | Prefixes/full-models, catalog/`owned_by`, optional pricing | After Phase 1 stable |
| 3 Live Grok quota | Only if spike found stable live source | Else cancel; keep manual plans |
| Later | Rename `claude_sidecar` → `cliproxy` | Separate change |

## Risks / Trade-offs

- **[Risk] Widen-before-adapter** → Mitigation: D3 atomicity + task order; tests that fail if Anthropic OAuth called for `xai`.
- **[Risk] Fake Claude bars on Grok** → Mitigation: `quota_windows` contract + frontend conditional render + estimate builder respect.
- **[Risk] Blended parent aggregate lies** → Mitigation: D4b null parent usage when multi-provider.
- **[Risk] Wrong Account label under concurrent mixed traffic** → Mitigation: prefer same-provider correlation; still possible miss → bare `CLIProxyAPI`.
- **[Risk] Priority banding docs wrong direction** → Mitigation: spike records CLIProxyAPI sort semantics.
- **[Risk] Wrong-provider credential burn under global fill-first** → Mitigation: spike probe; Settings warning if confirmed.
- **[Risk] Prefix collisions** → Mitigation: existing global uniqueness; no forced seeds.
- **[Risk] Claude pricing on Grok ids** → Mitigation: D6 cost rule + tests.
- **[Trade-off] Shared effort override** → Accept for this change.
- **[Trade-off] Keep internal id `claude`** → Avoid live rename churn; user-facing copy says CLIProxyAPI.

## Migration Plan

1. Iterate OpenSpec (this revision) until boring.
2. Phase 0 spike → update `context.md` / adjust Grok `quota_windows` defaults in design+specs if needed.
3. Implement Phase 1 atomically; restart only with operator OK.
4. Phase 2 routing/catalog; operators add `--xai-login` + prefixes.
5. Phase 3 only with proven live usage source.
6. Rollback = revert deploy; CLIProxyAPI remains SSOT for pause/priority/strategy.

## Open Questions (spike-bound)

1. Exact xAI auth-file `provider` / `type` / `account_type` strings.
2. Live weekly and/or five-hour fields for xAI (auth-file quota vs `api_call`).
3. Canonical Grok model ids from CLIProxyAPI `/v1/models`.
4. Usage-queue `provider` string for Grok vs auth-file provider (for correlation preference).
5. CLIProxyAPI priority sort direction (higher vs lower preferred).
6. Whether credential selection is model-family-aware under global fill-first with interleaved Claude+Grok priorities.
