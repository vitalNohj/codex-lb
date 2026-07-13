## 1. Phase 0 — Spike (no codex-lb code)

- [ ] 1.1 On an idle/non-prod CLIProxyAPI (or after confirming no active Grok traffic), run `cli-proxy-api --xai-login` (with `--no-browser` if using device/code flow) and confirm an xAI auth file lands in the configured auth-dir
- [ ] 1.2 Capture a redacted Management API `auth-files` payload for the new xAI entry (`provider`, `type`, `account_type`, quota fields, priority/disabled) into `openspec/changes/cliproxy-multi-provider-auth/context.md` or `notes.md`
- [ ] 1.3 Send one Grok/xAI chat through CLIProxyAPI and capture a redacted `usage-queue` record (`provider`, auth identity, tokens) into context/notes
- [ ] 1.4 Determine whether xAI exposes weekly and/or five-hour utilization via auth-file fields or management `api-call`; record adapter window declaration (`weekly` only vs `five_hour`+`weekly` vs manual-only)
- [ ] 1.5 List CLIProxyAPI `/v1/models` ids for Grok/xAI and note safe default prefix/full-model candidates that would not collide with existing OpenRouter/OmniRoute/Ollama rules
- [ ] 1.6 If spike findings invalidate a draft requirement (especially quota windows), update `design.md` / delta specs before implementation

## 2. Phase 1 — Auth ingestion and provider adapters (backend)

- [ ] 2.1 Remove Claude-only filters in quota parsing / routing account builders; ingest all auth files with usable `name` and normalize `provider` (unknown fallback)
- [ ] 2.2 Introduce a provider-adapter interface (Claude / Grok-xAI / default) for live usage attachment and declared quota windows
- [ ] 2.3 Gate Anthropic OAuth usage fetches behind the Claude adapter only; add a regression test that non-Claude auths never hit the Anthropic OAuth URL
- [ ] 2.4 Extend auth-plan / estimation storage to key by auth identity (+ provider) additively so Grok manual plans do not clobber Claude plans; preserve read compatibility with existing Claude plan JSON
- [ ] 2.5 Update `/api/claude-sidecar/routing` (+ pause/priority paths) to return and mutate all providers in one global pool; keep single strategy mapping (`round_robin`/`fill_first`)
- [ ] 2.6 Thread adapter-declared windows + provider through `sidecar_summary` / dashboard account schemas (`SidecarAuthAccount` and related)
- [ ] 2.7 Enforce request-log Account label helper: `CLIProxyAPI: <account>` / `CLIProxyAPI` only — no Claude/Grok qualifier; add/adjust unit tests

## 3. Phase 1 — Frontend surfaces

- [ ] 3.1 Update Settings CLIProxyAPI routing UI to render mixed-provider rows with provider labels in one priority/pause list and one strategy control
- [ ] 3.2 Update Dashboard CLIProxyAPI auth cards/list rows to render adapter-declared windows (omit five-hour when not declared; keep weekly when declared)
- [ ] 3.3 Extend Accounts quota-estimation / manual plan UI so non-Claude CLIProxyAPI auths can use the Claude-style input workflow without cross-writing Claude plans
- [ ] 3.4 Keep Request Logs Account cell formatting as `CLIProxyAPI: <label>` / `CLIProxyAPI`; add/adjust component test proving no provider qualifier is injected for Grok or Claude rows
- [ ] 3.5 Update Settings/Dashboard copy that still claims CLIProxyAPI is Claude-only where it would mislead operators (tab name stays CLIProxyAPI)

## 4. Phase 1 — Tests and validation gates

- [ ] 4.1 Backend tests: mixed Claude+Grok auth-files fixture → quota snapshot + routing list include both; pause/priority patch uses auth `name`
- [ ] 4.2 Backend tests: Claude adapter still attaches OAuth windows; Grok adapter skips Anthropic; manual plan estimate path for Grok
- [ ] 4.3 Frontend tests: routing list mixed providers; card window presence; request-log Account label non-regression
- [ ] 4.4 Run `openspec validate cliproxy-multi-provider-auth --strict` and keep deltas green after any spec edits from spike

## 5. Phase 2 — Grok routing and catalog labeling

- [ ] 5.1 Add operator-configurable CLIProxyAPI prefixes/full-models support verification for Grok ids (seed defaults only when uniqueness-safe per spike 1.5)
- [ ] 5.2 Add chat-completions tests: Grok full-model and prefix match dispatch through existing CLIProxyAPI sidecar path; unmatched `grok-*` does not force sidecar
- [ ] 5.3 Fix model catalog / dashboard model labels so non-Claude CLIProxyAPI models are not hard-labeled `Claude: …`
- [ ] 5.4 Optionally add Grok/xAI reference pricing rows; unpaid/unknown models stay `NULL` cost (not zero)
- [ ] 5.5 Document operator steps in change `context.md`: `--xai-login`, priority banding tips under global fill-first, prefix setup

## 6. Phase 3 — Live Grok quota enrichment (optional)

- [ ] 6.1 Only if spike found a stable live usage source: implement Grok adapter live weekly (and five-hour iff real) via Management API / auth-file fields
- [ ] 6.2 Prefer live % over manual estimates when both exist (mirror Claude OAuth preference)
- [ ] 6.3 If no stable source exists, mark Phase 3 cancelled/deferred in tasks and keep manual plans as the supported path

## 7. Apply readiness / live ops

- [ ] 7.1 Do **not** restart `codex-lb` until the operator confirms a safe window (shared live instance)
- [ ] 7.2 After implement+deploy, verify Claude cards/OAuth/pause still work on existing accounts before relying on Grok
- [ ] 7.3 Verify one Grok request: Dashboard card, routing row, request log Account `CLIProxyAPI: <email>`, model id shows Grok
- [ ] 7.4 Explicitly leave `claude_sidecar_*` → `cliproxy_*` rename out of this PR (follow-up change only)
