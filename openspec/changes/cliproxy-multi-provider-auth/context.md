# Context: CLIProxyAPI Multi-Provider Auth

## Purpose

Make codex-lb's CLIProxyAPI integration honest about multi-upstream auth files (Claude, Grok/xAI, future) while keeping one Settings integration, one Management API client, and one global routing/priority/pause pool — without shipping the “widen filter only” trap that would call Anthropic OAuth and invent Claude bars for Grok.

## Scope

- Provider adapters + concrete observation fields (`provider`, `quota_windows`, `supports_manual_plan`).
- Atomic widen of auth ingestion after/with those gates.
- Dashboard/Settings UI driven by those fields.
- Grok routing via existing CLIProxyAPI prefixes/full-models.
- Honest model catalog labels / `owned_by`.
- Request Logs Account stays `CLIProxyAPI: <account>`; prefer same-provider correlation.

## Non-goals

- `claude_sidecar` → `cliproxy` rename.
- Second integration card for same CLIProxyAPI URL.
- Provider names in Request Logs Account cells.
- Per-upstream effort overrides.
- CLIProxyAPI process/login ownership.
- Asserting model-family credential pick without spike proof.

## Decision rationale

| Decision | Why |
|----------|-----|
| Adapters before widen | Current poller calls Anthropic for every `auth_index`; estimates invent 5h/7d for everyone. Widen-first = operator-facing lies + bad upstream calls. |
| Concrete `quota_windows` API field | Frontend today hardcodes two bars; without a field, backend adapters cannot drive UI. |
| Auth plans stay JSON array + optional `provider` | Avoids migration rewrite; matches existing `ClaudeSidecarAuthPlan` list persistence. |
| Null parent aggregate when multi-provider | Parent synthetic summary currently blends all auth estimates into one Claude-shaped usage. |
| Prefer same-provider correlation | 30s nearest-event matching can mis-attribute under concurrent Claude+Grok traffic. |
| Keep resolver id `claude` | Live rename cost; means “CLIProxyAPI integration,” not “Claude-only.” |
| Shared effort override | Existing setting; per-upstream effort is a follow-up if Grok needs diverge. |

## Alternatives considered

1. **Widen filter only** — rejected (OAuth + fake bars).
2. **Full rename to cliproxy** — deferred.
3. **Separate Grok Settings tab** — rejected (shared pool + prefix uniqueness).
4. **Object-map auth plans** — rejected for this change; additive array field instead.
5. **Per-provider strategies in codex-lb** — rejected (CLIProxyAPI has one strategy endpoint).

## Constraints

- Live shared `codex-lb`: no unprompted restarts.
- Global prefix/full-model uniqueness across sidecars.
- Management API remains SSOT for pause/priority/strategy.
- Anthropic OAuth URL must not be called for non-Claude auths.
- Do not apply Anthropic pricing to non-Claude model ids (`NULL` if unknown).
- `spec.md` normative only; this file is narrative.

## Failure modes / edge cases

- Auth file missing `provider` → `unknown`; still listed; manual plans; subtitle fallback `CLIProxyAPI`.
- Auth file missing usable `name` → skipped (cannot target pause/priority).
- Usage-queue correlation miss → bare `CLIProxyAPI`.
- Concurrent mixed traffic without provider match signal → may still mis-associate; prefer-provider reduces but does not eliminate risk.
- Operator sets Grok highest priority under global fill-first while sending Claude models → **spike must verify** whether CLIProxyAPI still selects Claude credentials; if not, Settings needs a warning.
- Priority banding docs wrong if CLIProxyAPI sort direction ≠ UI “higher preferred” copy → spike records truth.
- Manual Claude `pro` default applied to new Grok estimation row → forbidden by frontend requirement.
- Blended parent usage with mixed providers → forbidden; cards carry truth.
- Grok model discovered via CLIProxyAPI `/v1/models` labeled `Claude: …` / `owned_by: anthropic` → forbidden.

## Example flows

### Add Grok to existing CLIProxyAPI (after Phase 1+2)

1. `cli-proxy-api --xai-login` into the same auth-dir.
2. Management `auth-files` gains xAI entry (exact `provider` string from spike).
3. Settings routing shows Claude + Grok rows with provider labels; one strategy.
4. Dashboard shows a Grok auth card; bars follow `quota_windows`; else manual estimation.
5. Operator sets priorities in one list (banding per verified CLIProxyAPI sort direction).
6. Operator adds Grok prefixes/full-models under CLIProxyAPI integration.
7. Cursor request → CLIProxyAPI dispatch → request log Account `CLIProxyAPI: <email>`; Model shows Grok id.

### Priority list sketch (global; direction TBD by spike)

```
Strategy: fill-first

Priority  Account                         Provider   Paused
???       vitalnohj@gmail.com             Claude     no
???       jvwarrior@gmail.com             Claude     no
???       grok-user@example.com           Grok       no
```

Replace `???` after spike confirms higher-vs-lower preferred.

## Phase 0 spike checklist (record answers in notes/context)

1. Redacted xAI auth-file JSON: `provider`, `type`, `account_type`, quota fields, priority/disabled.
2. Redacted usage-queue row for one Grok chat (`provider`, auth identity).
3. Live weekly / five-hour availability (auth-file vs `api_call`).
4. `/v1/models` Grok ids + safe prefix candidates (uniqueness check).
5. Priority sort direction under Management API.
6. Family-selection probe: interleaved priorities + Claude model request + Grok model request — which auth_index burns?

## Operational notes

- Do not pre-hash CLIProxyAPI management secrets.
- Pause/Resume still PATCHes `disabled` by auth-file `name`.
- Implementation PR must keep adapter+poller+estimate gates atomic with filter widen.
- Follow-ups: rename to `cliproxy`; per-upstream effort; Kimi adapter; live Grok quota if discovered.

## Related

- This change’s `proposal.md` / `design.md` / `tasks.md` / `specs/*`.
- Prior art: `add-claude-sidecar-routing`, `add-cliproxy-routing-controls`, `add-cliproxy-account-pause`, `cliproxy-card-codex-parity`, `normalize-sidecar-request-log-display`, `move-integration-controls-to-accounts`.
