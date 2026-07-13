## Context

CLIProxyAPI (currently wired in codex-lb as the `claude_sidecar` integration) already authenticates multiple upstreams into one process: Claude OAuth, xAI/Grok OAuth (`-xai-login`), and additional provider logins. codex-lb talks to one `base_url` + API key for chat, and one Management API key for auth-files / routing strategy / pause / usage-queue.

Today the **transport** path is mostly provider-agnostic (prefix/full-model match → `proxy_chat_to_sidecar`). The **observation and control** path is not: `quota.py::_is_claude_entry` and `service.py::_routing_accounts` drop non-Claude auth files; OAuth usage always hits Anthropic; Dashboard cards assume 5h + weekly Claude bars; Settings copy and model catalog labels say Claude.

This design implements the locked exploration decisions: generic multi-provider shell, provider-plugin observation adapters, **one global** CLIProxyAPI routing pool, Codex-parity cards with provider-specific quota windows (manual estimate fallback), and Request Logs Account cells that stay `CLIProxyAPI: <account>` with no Claude/Grok qualifier.

codex-lb is live. This OpenSpec change is planning-first; implementation must be staged and restart-gated.

## Goals / Non-Goals

**Goals:**

- Surface every CLIProxyAPI auth file (Claude, Grok/xAI, future) in routing, pause/priority, and Dashboard cards.
- Keep one global `round_robin` / `fill_first` strategy and one priority namespace across those auths.
- Make quota/usage observation correct per provider via adapters (live OAuth/usage when available; else Claude-style manual auth-plan inputs).
- Route Grok/xAI models through the existing CLIProxyAPI sidecar entry without a second integration card.
- Preserve Request Logs Account format: `CLIProxyAPI: <account email/label>`.

**Non-Goals:**

- Rename `claude_sidecar_*` persistence/API paths to `cliproxy_*` (follow-up).
- Duplicate External Integrations tab for the same CLIProxyAPI URL.
- Inject provider names into Request Logs Account cells.
- Own CLIProxyAPI login UX or process supervision.
- Change OpenRouter / OmniRoute / Ollama / native Codex LB behavior.
- Guarantee Anthropic-shaped 5h windows for every provider.

## Decisions

### D1 — One integration, provider adapters (Option 2)

**Choice:** Keep the single CLIProxyAPI Settings tab and `claude_sidecar_*` settings keys. Add an internal provider-adapter registry keyed by normalized auth `provider` (and fallbacks from `type` / auth-file naming when needed).

**Adapter responsibilities (observation only):**

| Concern | Claude adapter | Grok/xAI adapter (v1) | Default / unknown |
|--------|----------------|------------------------|-------------------|
| Live usage % | Anthropic OAuth via management `api_call` (existing) | Derive from CLIProxyAPI/xAI if Phase-0 spike finds a stable source; else skip live % | Skip live % |
| Quota windows on card | 5h + weekly (existing) | Weekly when known; 5h only if exposed | Show manual-estimate windows only |
| Manual auth plans | Existing `claude_sidecar_auth_plans` / Accounts estimation UI | Same UX pattern, keyed per auth identity + provider | Same |
| Pricing / reference cost | Existing Anthropic table | Add xAI/Grok rows when routing ships; else `NULL` cost | `NULL` |

**Alternatives rejected:**

- Option 1 (widen filter only): ships faster but leaves Claude OAuth/bars on Grok rows → operator lies.
- Option 3 (rename to `cliproxy`): correct long-term naming, but large migration while live; defer.
- Separate Grok integration card: fights global prefix uniqueness and shares one CLIProxyAPI routing pool awkwardly.

### D2 — Global credential pool (locked)

**Choice:** Treat CLIProxyAPI's routing strategy + per-auth `priority` / `disabled` as **one global pool** across providers. Settings routing UI lists all auth files, visually grouped or labeled by provider, but operators edit one strategy and one priority namespace.

**Rationale:** Matches CLIProxyAPI's Management API shape (`GET/PUT routing/strategy`, `PATCH auth-files/fields` by auth-file `name`) and the operator's locked decision that selection is global `fill-first` / `round-robin`.

**Operational implication:** Under `fill-first`, priority ordering can interleave Claude and Grok auths. That is intentional. Model routing still depends on CLIProxyAPI matching credentials to the requested upstream model family; codex-lb does not invent per-provider strategy forks in this change. Document this clearly in operator context so interleaved priorities are not surprising.

**UI requirement:** Every routing row MUST show provider + account identity so interleaved priorities are readable.

### D3 — Auth ingestion: include all, classify by provider

**Choice:** Replace Claude-only filters with:

1. Accept all management auth-file entries that have a usable `name` (auth-file identity).
2. Normalize `provider` for each row (`claude`, `xai`/`grok`, …) from upstream fields; unknown → `unknown` (still shown).
3. Attach the matching adapter for observation; control plane (pause/priority) is provider-agnostic.

**Synthetic account summary:** Keep one synthetic CLIProxyAPI parent for Settings/Accounts navigation if needed, but Dashboard continues **one card per auth** (already Codex-parity). Each card's subtitle uses `<plan-or-tier> | <ProviderLabel>` where ProviderLabel is humanized (`Claude`, `Grok`/`xAI`, `CLIProxyAPI` fallback) — this is card chrome, **not** the Request Logs Account cell.

### D4 — Quota widget contract

**Choice:** Shared card chrome; window set is adapter-declared:

- `windows: ["five_hour", "weekly"]` — Claude today
- `windows: ["weekly"]` — expected Grok v1 if only weekly is known
- `windows: ["five_hour", "weekly"]` — if spike proves Grok exposes both
- Empty live windows + `supports_manual_plan: true` — show estimation inputs / estimated bars like Claude manual plans

Manual plans MUST be keyed so Claude plans do not overwrite Grok plans for different auth identities. Prefer extending auth-plan JSON to `{ auth_key: { provider, plan_type, budgets... } }` with backward-compatible read of today's Claude-shaped plans.

### D5 — Request Logs Account labeling (locked)

**Choice:** Keep / enforce:

- Matched: `CLIProxyAPI: <email or auth label>`
- Unmatched: `CLIProxyAPI`

**MUST NOT** append `(Grok)`, `Grok:`, `Claude:`, or similar to the Account cell. Model id remains the provider signal. Correlation continues to use usage-queue proximity (existing 30s window); usage events already carry `provider` for diagnostics but UI Account text ignores it.

### D6 — Grok routing through existing sidecar entry

**Choice:** Operator configures prefixes/full-models on the CLIProxyAPI integration (seed suggested defaults such as `grok` / `grok-` only if they do not collide with existing unique-prefix rules). Dispatch stays `provider="claude"` in the internal sidecar resolver key for this change (meaning “CLIProxyAPI integration”), deferred rename notwithstanding.

Model catalog / dashboard model labels MUST use a neutral or provider-accurate prefix (e.g. `CLIProxyAPI: <id>` or upstream-informed label), not hard-coded `Claude: <id>` for non-Claude models.

### D7 — Phased delivery (live-safe)

| Phase | Scope | Restart? |
|-------|-------|----------|
| 0 Spike | Non-prod or idle CLIProxyAPI: `-xai-login`, dump auth-files + usage-queue + any usage endpoints; record window shape | CLIProxyAPI only |
| 1 Auth surface | Widen ingestion; adapters; cards/routing UI; skip Anthropic OAuth for non-Claude; manual plans for Grok | codex-lb when implementing |
| 2 Grok routing | Prefixes/full-models, catalog labels, optional pricing | codex-lb when implementing |
| 3 Quota enrichment | Wire live Grok usage if spike found a stable source | codex-lb when implementing |
| Later | Optional rename `claude_sidecar` → `cliproxy` | separate change |

OpenSpec artifacts cover Phases 1–3 requirements; Phase 0 is a gated task that may adjust adapter window declarations before apply.

## Risks / Trade-offs

- **[Risk] Global fill-first interleaves providers** → Mitigation: provider-labeled priority rows + context docs; operators set Claude priorities in a contiguous high band if they want Claude preferred for ambiguous cases. Do not silently split strategies.
- **[Risk] Anthropic OAuth called for Grok auths** → Mitigation: adapter gate; only Claude adapter invokes `oauth_usage.py`.
- **[Risk] Misleading 5h bars on Grok** → Mitigation: adapter-declared windows; omit 5h unless proven.
- **[Risk] Auth-plan schema drift** → Mitigation: additive JSON; read old Claude plans; tests for mixed Claude+Grok plan maps.
- **[Risk] Prefix collisions** across CLIProxyAPI/OpenRouter/OmniRoute/Ollama → Mitigation: reuse existing global uniqueness validators; do not force-seed colliding defaults.
- **[Risk] Live restart mid-traffic** → Mitigation: implement only after OpenSpec iterate; restart only with operator OK (codex-lb shared).
- **[Risk] Internal resolver still named `claude`** → Mitigation: document as “CLIProxyAPI integration id”; rename deferred; avoid new user-facing “Claude-only” copy in Settings for the tab that already says CLIProxyAPI.
- **[Trade-off] One shared CLIProxyAPI reasoning-effort override** remains for this change → Acceptable short-term; per-upstream effort overrides can be a follow-up if Grok vs Claude effort needs diverge.

## Migration Plan

1. Land OpenSpec only; iterate proposal/design/deltas until boring.
2. Run Phase 0 spike; update `context.md` with real auth-file + window findings; adjust Grok adapter requirements if needed.
3. Implement Phase 1 behind normal PR gates; no behavior change until deploy/restart.
4. Implement Phase 2 routing; operators add prefixes and `--xai-login` auth files.
5. Phase 3 only if live usage source exists; otherwise keep manual plans.
6. Rollback: revert deploy; CLIProxyAPI auth files and strategy remain source of truth (codex-lb observation is non-authoritative for pause/priority).

## Open Questions

Resolved by operator lock-in (see proposal). Remaining spike-bound questions (do not block drafting; block Phase 3 / window declarations):

1. Exact auth-file `provider` / `type` strings CLIProxyAPI emits for xAI (`xai` vs `grok` vs other).
2. Whether xAI exposes weekly and/or 5h utilization via management `api_call` or auth-file quota fields.
3. Canonical Grok model ids advertised on CLIProxyAPI `/v1/models` for default prefix suggestions.
4. Whether usage-queue `provider` for Grok matches the auth-file provider string (needed only for diagnostics; not for Account label text).
