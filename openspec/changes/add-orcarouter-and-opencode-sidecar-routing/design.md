## Context

codex-lb already has four External Integrations (CLIProxyAPI, OpenRouter, OmniRoute, Ollama). Shared contract: dashboard settings + unified `resolve_sidecar_route()` + chat-completions dispatch + synthetic account + Request Logs labels.

OrcaRouter and OpenCode Free already work *through* OmniRoute. This change clones the OpenRouter HTTP sidecar (not the Ollama SDK adapter) so those two providers can be enabled without OmniRoute owning the hop.

OrcaRouter (`https://api.orcarouter.ai/v1`) is a paid OpenAI-compatible gateway using `sk-orca-` keys. Its adaptive router id is `orcarouter/auto`; a bare `auto` id returns 503. Pinned models use vendor namespaces (`openai/gpt-5.5`) that collide with OpenRouter prefixes if seeded globally.

OpenCode Free (`https://opencode.ai/zen/v1`) is keyless. Live catalog ids are bare (`big-pickle`); client-facing ids stay prefixed (`oc/big-pickle`). OmniRoute's executor also does fingerprint/proxy rotation and optional Cloudflare CLI headers; this change keeps a single direct HTTP client.

## Goals / Non-Goals

**Goals:**

- First-class Settings tabs, routing, catalog, logs, and accounts for OrcaRouter and OpenCode Free.
- OpenAI-compatible HTTP relay on `/v1/chat/completions` only.
- Preserve prefix/full-model uniqueness against existing integrations.
- Keyless OpenCode Free health, discovery, and dispatch.
- Operator reasoning-effort override and DeepSeek V4 repair on both paths.

**Non-Goals:**

- MiMoCode, DeepSeek Web, OpenCode Zen paid, OpenCode Go.
- OmniRoute combo stacks or executor ports.
- `/v1/responses` dispatch.
- Fingerprint/proxy rotation, Playwright, PoW.
- Seeding OrcaRouter with `openai/` / `google/` / `anthropic/` / `deepseek/` prefixes.

## Decisions

### 1. Clone OpenRouter HTTP, not OmniRoute executors

**Choice:** Two new clients + dispatch modules using `aiohttp` like OpenRouter.

**Why:** Both upstreams already speak OpenAI chat completions. Porting OmniRoute's TypeScript executors (rotation, PoW, combo failover) into Python is the wrong layer.

**Alternative considered:** Keep routing through OmniRoute and only add UI labels. Rejected because the operator asked for first-class integrations for these two providers.

### 2. Two integrations, one OpenSpec change

**Choice:** One change, two provider order entries, two tabs, one migration.

**Why:** Same architectural pattern; user scoped both together. Implementation tasks sequence OrcaRouter first (API-key twin of OpenRouter), then OpenCode Free (keyless delta).

**Alternative considered:** Two changes. Cleaner PRs, slower, and shared uniqueness/order edits would conflict.

### 3. Provider order

**Choice:** `("claude", "openrouter", "orcarouter", "omniroute", "opencode", "ollama")`.

**Why:** OrcaRouter sits with the other API-key gateways. OpenCode Free sits after OmniRoute so an accidental dual `oc/` config still has a deterministic tie-break, while settings uniqueness should reject the overlap on save.

### 4. Seeded prefixes

**Choice:**

| Integration | Seeded prefixes | Strip |
|---|---|---|
| OrcaRouter | `orcarouter/` | off |
| OpenCode Free | `oc/`, `opencode/` | on |

Pinned OrcaRouter vendor ids are operator-added **full models** so they beat OpenRouter prefixes without stealing `openai/*` wholesale.

**Alternative considered:** Seed `openai/` on OrcaRouter. Rejected: it would take all OpenRouter `openai/` traffic.

### 5. OpenCode Free has no required API key

**Choice:** Empty key omits `Authorization`. Dashboard "configured" / synthetic account / test-connection treat **enabled** as sufficient. OrcaRouter still requires a stored key for chat dispatch and a successful test.

**Why:** OpenCode Free is a public zen endpoint. Gating on key would make the tab unusable.

### 6. Attribution headers for OrcaRouter

**Choice:** Send `HTTP-Referer` and `X-Title` identifying codex-lb, plus a dedicated User-Agent, matching how OmniRoute's OrcaRouter registry attributes traffic.

**Why:** Gateways often use these for ranking/abuse. OpenRouter's current client does not send them; adding them only on OrcaRouter is enough.

### 7. OpenCode User-Agent, no CLI-header synthesizer in v1

**Choice:** `User-Agent: codex-lb/opencode-sidecar`. Do not port `OPENCODE_SYNTHESIZE_CLI_HEADERS` or per-account proxies.

**Why:** Smallest path. If Cloudflare blocks datacenter IPs, operator can keep using OmniRoute for OpenCode or we add headers later.

### 8. Effort override and DeepSeek V4

**Choice:** Reuse `set_reasoning_effort_override` and hook `deepseek_v4_compat` on both chat paths, same as OpenRouter/OmniRoute.

**Why:** OpenCode Free serves DeepSeek V4 thinking models (`deepseek-v4-flash-free`, `big-pickle`). OrcaRouter can pin DeepSeek vendor ids as full models.

### 9. Cost

**Choice:** OpenCode Free uses existing `is_known_free_model` (`-free` regex + `oc/big-pickle` opaque allowlist). OrcaRouter: record usage; `cost` stays null without a pricing row.

### 10. UI

**Choice:** Two `bare` tab components in `sidecar-integrations.tsx`. Enable toggle above the callout. OpenCode Free hides or optionalizes the API-key row. Labels: `OrcaRouter`, `OpenCode Free` — never "sidecar".

### 11. Responses

**Choice:** Chat-completions only, same as OpenRouter/Ollama first pass.

## Risks / Trade-offs

- [OpenCode Free ToS / Cloudflare] → Keyless public endpoint; OmniRoute tags some catalog rows `tos: "avoid"`. Mitigate by keeping OmniRoute as fallback and not synthesizing CLI fingerprints in v1.
- [Prefix clash with live OmniRoute `oc/`] → Uniqueness rejects save. Mitigate with docs in Settings callout: disable or remove OmniRoute `oc/` / `opencode/` before enabling OpenCode Free.
- [OrcaRouter `orcarouter/auto` vs bare `auto`] → Seed strip-off prefix; never strip `orcarouter/`.
- [Vendor id overlap] → Full-model rows only; no seeded `openai/` on OrcaRouter.
- [PR size] → Two sidecars is roughly 2× Ollama. Mitigate by cloning OpenRouter mechanically and sequencing tasks; split PRs only if review requires it.
- [OpenCode client vs OpenCode Free logs] → Distinct source `opencode_sidecar` and label `OpenCode Free` so `useragent_group=opencode` stays the client.

## Migration Plan

1. Add nullable/defaulted columns on `dashboard_settings` in one Alembic revision on the current head.
2. Seed default prefix JSON for each integration; leave `enabled=false`.
3. Deploy code that understands the new columns before flipping either integration on.
4. Rollback: downgrade drops only the new columns; existing sidecar settings stay.

## Open Questions

- Whether production OmniRoute already owns `oc/` / `opencode/` (operator must clear before enabling the new tab).
- Whether Cloudflare in front of `opencode.ai` will require CLI-like headers from this host; defer until observed.
