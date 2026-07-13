# Context: CLIProxyAPI Multi-Provider Auth

## Purpose

Make codex-lb's CLIProxyAPI integration honest about multi-upstream auth files (Claude, Grok/xAI, future providers) while keeping one Settings integration, one Management API client, and one global routing/priority/pause pool.

## Scope

- Observation adapters per provider (usage windows, OAuth/live %, manual plans).
- Auth ingestion + Dashboard/Settings surfaces for all CLIProxyAPI auths.
- Grok/xAI routing via existing CLIProxyAPI prefixes/full-models.
- Request Logs Account stays `CLIProxyAPI: <account>` (no provider qualifier).

## Non-goals

- `claude_sidecar` → `cliproxy` rename.
- Second integration card for the same CLIProxyAPI URL.
- Provider names in Request Logs Account cells.
- CLIProxyAPI process/login ownership.

## Decision rationale

| Decision | Why |
|----------|-----|
| Generic multi-provider (not Grok-only) | CLIProxyAPI already ships multiple `-*-login` flows; a Grok-only fork would be rework for Kimi/etc. |
| Provider plugins | Transport is shared; observation is not. Adapters prevent Claude OAuth/bars from lying on Grok rows without a full rename. |
| Global fill-first / priority | Matches Management API + operator preference; UI must label provider so interleaved priorities are readable. |
| Same card chrome, adaptive windows | Operators already know Codex-parity cards; only the quota windows/inputs change per provider. |
| Manual plans fallback | Proven Claude path; unblocks Grok before a live xAI usage API is confirmed. |
| Flat Account log label | Model column already distinguishes providers; Account is for which credential burned. |

## Alternatives considered

1. **Widen filter only** — rejected (misleading quota/OAuth).
2. **Full rename to cliproxy** — deferred (live migration cost).
3. **Separate Grok Settings tab** — rejected (shared pool + prefix uniqueness).
4. **Per-provider routing strategies in codex-lb** — rejected for this change (CLIProxyAPI has one strategy endpoint).

## Constraints

- Live shared `codex-lb` instance: no unprompted restarts.
- Global prefix/full-model uniqueness across CLIProxyAPI/OpenRouter/OmniRoute/Ollama.
- Management API remains SSOT for pause/priority/strategy.
- Anthropic OAuth URL must not be called for non-Claude auths.
- Caveman/OpenSpec: `spec.md` normative only; this file is narrative.

## Failure modes / edge cases

- Auth file with missing/unknown `provider` → still listed; adapter = default/manual; subtitle fallback `CLIProxyAPI`.
- Usage-queue correlation miss → Account shows bare `CLIProxyAPI` (unchanged benign miss).
- Operator sets Grok auth to highest fill-first priority while sending Claude models → CLIProxyAPI should still select Claude credentials for Claude models; if upstream behavior differs, document from spike and revisit.
- Manual plan present but live OAuth also present (Claude) → existing preference: authoritative OAuth % wins when available.
- Prefix seed collides → do not auto-add; surface validation error.

## Example flows

### Add Grok to an existing CLIProxyAPI

1. Operator runs `cli-proxy-api --xai-login --no-browser` (or with browser) against the same auth-dir.
2. Management `auth-files` gains an xAI entry (`provider` per spike).
3. After Phase 1 deploy: Settings routing list shows Claude + Grok rows; Dashboard shows a Grok auth card with weekly (and 5h iff known) or manual estimate inputs.
4. Operator sets priorities in one list (e.g. Claude Max `100`, Grok `50`).
5. Operator adds `grok-` (or concrete full model ids) under CLIProxyAPI prefixes/full-models.
6. Cursor request for that model → codex-lb CLIProxyAPI dispatch → CLIProxyAPI selects xAI credential.
7. Request log Account: `CLIProxyAPI: user@x.ai` (example); Model shows the Grok model id.

### Priority list sketch (global)

```
Strategy: fill-first

Priority  Account                         Provider   Paused
100       vitalnohj@gmail.com             Claude     no
 90       jvwarrior@gmail.com             Claude     no
 50       grok-user@example.com           Grok/xAI   no
```

## Operational notes

- Spike before Phase 3: capture real xAI auth-file JSON + any quota fields + usage-queue sample (redact secrets) into this context or `notes.md`.
- Do not pre-hash CLIProxyAPI management secrets (existing rule).
- Pause/Resume still PATCHes `disabled` by auth-file `name`.
- Pricing: add Grok list prices only when routing ships; unpaid/unknown → `NULL` cost (not zero).
- Follow-up candidates: `claude_sidecar` rename; per-upstream effort overrides; Kimi adapter.

## Related

- Change proposal/design/tasks in this folder.
- Prior art: `add-claude-sidecar-routing`, `add-cliproxy-routing-controls`, `add-cliproxy-account-pause`, `cliproxy-card-codex-parity`, `normalize-sidecar-request-log-display`, `move-integration-controls-to-accounts`.
- Normative requirements: `specs/*/spec.md` in this change (not duplicated here).
