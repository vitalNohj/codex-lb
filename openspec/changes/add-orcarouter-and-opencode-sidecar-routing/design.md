## Context

codex-lb already has four External Integrations (CLIProxyAPI, OpenRouter, OmniRoute, Ollama). Shared contract: dashboard settings + unified `resolve_sidecar_route()` + chat-completions dispatch + synthetic account + Request Logs labels.

OrcaRouter, OpenCode Zen, and OpenCode Free already work *through* OmniRoute. This change clones the OpenRouter HTTP sidecar (aiohttp `GET /models` + `POST /chat/completions`, not the Ollama SDK) so those three can be enabled without OmniRoute owning the hop.

Live facts used for this design (2026-08-25):

- OrcaRouter: `https://api.orcarouter.ai/v1`, Bearer `sk-orca-…`, 190 models on the operator key, **no Xiaomi MiMo** in catalog. Adaptive id `orcarouter/auto`; bare `auto` returns 503.
- OpenCode Zen and OpenCode Free share `https://opencode.ai/zen/v1`. Live catalog lists 64 models including `mimo-v2.5-free` and `big-pickle`. Official Zen docs: those free SKUs are limited-time and may train on prompts.
- OmniRoute's `oc/` path is the keyless "OpenCode Free" provider. OmniRoute's `opencode-zen/` path is the same URL with optional key / anonymous fallback. Cursor already uses `opencode-zen/mimo-v2.5-free`.

## Goals / Non-Goals

**Goals:**

- First-class Settings tabs, routing, catalog, logs, and accounts for OrcaRouter, OpenCode Zen, and OpenCode Free.
- OpenAI-compatible HTTP relay on `/v1/chat/completions` only.
- Preserve prefix/full-model uniqueness against existing integrations.
- Keyless OpenCode Free health, discovery, and dispatch.
- Key-required OrcaRouter and OpenCode Zen health, discovery, and dispatch.
- Operator reasoning-effort override and DeepSeek V4 repair on all three paths.

**Non-Goals:**

- MiMoCode, DeepSeek Web, OpenCode Go.
- OmniRoute combo stacks or executor ports.
- `/v1/responses` or Zen `/messages` (GPT/Claude on Zen).
- Fingerprint/proxy rotation, Playwright, PoW.
- Seeding OrcaRouter with `openai/` / `google/` / `anthropic/` / `deepseek/` prefixes.
- Uninstalling OmniRoute.

## Decisions

### 1. Clone OpenRouter HTTP, not OmniRoute executors and not Ollama SDK

**Choice:** Three new clients + dispatch modules using `aiohttp` like `app/core/clients/openrouter_sidecar.py`.

**Why:** All three upstreams already speak OpenAI chat completions. Ollama used `import ollama`; that is the wrong template.

### 2. Three integrations, one OpenSpec change

**Choice:** One change, three provider-order entries, three tabs, one migration.

**Why:** Same architectural pattern; operator scoped all three together. Implementation sequences OrcaRouter first (API-key twin of OpenRouter), OpenCode Zen second (same twin, different URL/prefix), OpenCode Free third (keyless delta on the zen URL).

**Alternative considered:** Two changes (Orca vs OpenCode). Rejected: Zen and Free share a host and uniqueness rules; splitting would conflict on `SIDECAR_PROVIDER_ORDER` and Settings fixtures.

### 3. Provider order

**Choice:** `("claude", "openrouter", "orcarouter", "opencode-zen", "omniroute", "opencode", "ollama")`.

**Why:** API-key gateways stay together. OpenCode Free sits after OmniRoute so an accidental dual `oc/` config still has a deterministic tie-break. Settings uniqueness must reject the overlap on save.

### 4. Seeded prefixes

**Choice:**

| Integration | Seeded prefixes | Strip | Why |
|---|---|---|---|
| OrcaRouter | `orcarouter/` | off | `orcarouter/auto` must be forwarded unchanged |
| OpenCode Zen | `opencode-zen/` | on | Matches current Cursor/OmniRoute ids; catalog ids are bare (`mimo-v2.5-free`) |
| OpenCode Free | `oc/` | on | Matches current `oc/big-pickle` ids; catalog ids are bare |

Do **not** seed `opencode/` on Free. Official OpenCode TUI uses `opencode/<id>` for Zen. Seeding it on Free would send `opencode/mimo-v2.5-free` to the keyless pool.

Pinned OrcaRouter vendor ids are operator-added **full models** so they beat OpenRouter prefixes without stealing `openai/*` wholesale.

### 5. OpenCode Free has no required API key; Zen does

**Choice:** Free omits `Authorization` when the key is empty. Dashboard "configured" / synthetic account / test-connection treat **enabled** as sufficient for Free. OrcaRouter and OpenCode Zen still require a stored key for chat dispatch and a successful test.

**Why:** Free is OmniRoute's no-auth zen endpoint. Zen is the official signed-in gateway that actually hosts `mimo-v2.5-free` reliably.

### 6. Same zen URL for Zen and Free is allowed

**Choice:** Two settings rows, two sources, two clients, one default base URL.

**Why:** Auth and prefixes differ. Do not merge them into one tab with an optional key; the operator asked for both named integrations.

### 7. Attribution headers

**Choice:** OrcaRouter sends `HTTP-Referer`, `X-Title`, and `User-Agent: codex-lb/orcarouter-sidecar`. OpenCode Zen/Free send `User-Agent: codex-lb/opencode-zen-sidecar` and `codex-lb/opencode-sidecar`. Do not port OmniRoute CLI-header synthesizers.

### 8. Effort override and DeepSeek V4

**Choice:** Reuse `set_reasoning_effort_override` and hook `deepseek_v4_compat` on all three chat paths.

**Why:** Free and Zen serve DeepSeek V4 thinking models and `big-pickle`. OrcaRouter can pin DeepSeek vendor ids as full models.

### 9. Cost

**Choice:** `-free` regex plus opaque allowlist (`big-pickle`, `oc/big-pickle`, `opencode-zen/big-pickle`). OrcaRouter: record usage; `cost` stays null without a pricing row. Orca free catalog rows with `pricing.request = 0` are still not a full prompt/completion table — do not invent per-token prices; use `is_known_free_model` / null.

### 10. UI

**Choice:** Three `bare` tab components in `sidecar-integrations.tsx`. Enable toggle above the callout. OpenCode Free hides or optionalizes the API-key row. Labels: `OrcaRouter`, `OpenCode Zen`, `OpenCode Free` — never "sidecar".

### 11. Responses

**Choice:** Chat-completions only, same as OpenRouter/Ollama first pass. Zen GPT models that only work on `/v1/responses` are out of scope.

### 12. OmniRoute coexistence

**Choice:** Do not auto-disable OmniRoute. Uniqueness rejects save if OmniRoute still owns `orcarouter/` or `oc/`. Settings callouts must say: remove those OmniRoute prefixes/full models before enabling the new tabs.

## Risks / Trade-offs

- [OpenCode Free ToS / Cloudflare / 503] → Keyless public endpoint is the flaky path the operator already hates. Ship it because they asked; do not pretend it is as reliable as Zen-with-key.
- [Prefix clash with live OmniRoute] → Uniqueness rejects save. Callout tells the operator to clear OmniRoute `orcarouter/` / `oc/` / `opencode-zen/` first.
- [OrcaRouter `orcarouter/auto` vs bare `auto`] → Seed strip-off prefix; never strip `orcarouter/`.
- [Vendor id overlap] → Full-model rows only; no seeded `openai/` on OrcaRouter.
- [PR size] → Three sidecars is roughly 3× Ollama. Mitigate by cloning OpenRouter mechanically and sequencing tasks; split PRs only if review requires it (Orca first, then Zen+Free).
- [OpenCode client vs OpenCode Free logs] → Distinct sources `opencode_sidecar` / `opencode_zen_sidecar` so `useragent_group=opencode` stays the client.
- [Synthetic account fallthrough] → `synthetic-account-detail.tsx` currently treats anything that is not OpenRouter/OmniRoute as Claude. New providers MUST get explicit branches so they do not show Claude pause/quota UI.

## Migration Plan

1. Add nullable/defaulted columns on `dashboard_settings` in one Alembic revision on the current head (`20260818_000000_backfill_claude_opus_5_sonnet_5_costs` unless a newer head lands first — re-check before writing the revision).
2. Seed default prefix JSON for each integration; leave `enabled=false`.
3. Deploy code that understands the new columns before flipping any integration on.
4. Rollback: downgrade drops only the new columns; existing sidecar settings stay.

## Open Questions

- Whether production OmniRoute already owns `orcarouter/` / `oc/` / `opencode-zen/` (operator must clear before enabling the new tabs). Live this host: OmniRoute prefixes are `cx/` and `orcarouter/`; selected models include `oc/big-pickle` and `opencode-zen/mimo-v2.5-free`.
- Whether Cloudflare in front of `opencode.ai` will require CLI-like headers from this host; defer until observed.
