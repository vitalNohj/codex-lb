## 1. Phase 0 — Spike (no codex-lb code; gates Phase 1 window defaults)

- [ ] 1.1 On idle/non-prod CLIProxyAPI (or after confirming no active Grok traffic), run `cli-proxy-api --xai-login` and confirm an xAI auth file lands in the auth-dir
- [ ] 1.2 Capture redacted Management API `auth-files` fields for the xAI entry (`provider`, `type`, `account_type`, quota fields, priority/disabled) into `context.md` or `notes.md`
- [ ] 1.3 Send one Grok/xAI chat through CLIProxyAPI; capture redacted `usage-queue` (`provider`, auth identity, tokens)
- [ ] 1.4 Determine live weekly and/or five-hour utilization sources; set Grok adapter `quota_windows` default (`[]`, `["weekly"]`, or `["five_hour","weekly"]`)
- [ ] 1.5 List CLIProxyAPI `/v1/models` Grok/xAI ids; note uniqueness-safe prefix/full-model candidates vs OpenRouter/OmniRoute/Ollama
- [ ] 1.6 Record CLIProxyAPI priority sort direction (higher vs lower preferred) and align Settings help / banding docs
- [ ] 1.7 Probe global fill-first with interleaved Claude+Grok priorities: which auth burns for a Claude model vs a Grok model; document family-aware vs not; add Settings warning requirement if wrong-provider burn is possible
- [ ] 1.8 If spike invalidates draft window/provider-string requirements, update `design.md` + delta specs before implementation

## 2. Phase 1 — Adapters and gates BEFORE / with filter widen (backend)

- [x] 2.1 Add provider-adapter registry (Claude / xAI / default) with normalized provider keys and declared `quota_windows` + `supports_manual_plan`
- [x] 2.2 Gate `quota_poller` Anthropic OAuth attachment behind Claude adapter only; regression test: xAI auth in fixture ⇒ zero Anthropic OAuth calls
- [x] 2.3 Refactor/wrap `build_claude_usage_estimates` so non-Claude auths do not receive invented Claude 5h/7d plan math; respect adapter windows
- [x] 2.4 Extend `SidecarAuthAccount` (and frontend schema) with `quota_windows` + `supports_manual_plan`; keep/normalize `provider`
- [x] 2.5 Extend `ClaudeSidecarRoutingAccount` (and frontend schema) with `provider`
- [x] 2.6 Extend auth-plan array rows with optional `provider`; preserve legacy Claude rows; non-Claude plans use `custom` with budgets only for applicable windows
- [x] 2.7 Only after 2.1–2.3 exist: remove Claude-only filters in `quota.py` / `_routing_accounts`; ingest all usable non-empty `name`s
- [x] 2.8 Update routing/pause/priority service paths to return all providers in one global pool
- [x] 2.9 Parent synthetic summary: when multiple providers present, omit blended parent `usage` aggregate (D4b)
- [x] 2.10 Request-log correlation: prefer same-provider usage event in the 30s window; Account text stays `CLIProxyAPI: <account>` / `CLIProxyAPI` (regression tests)

## 3. Phase 1 — Frontend surfaces

- [x] 3.1 Settings routing UI: mixed-provider rows with provider labels; one strategy control; provider-neutral empty-state copy
- [x] 3.2 `ClaudeAuthCard` / `ClaudeAuthListRow` / `SyntheticAccountDetail`: render bars only from `quota_windows`
- [x] 3.3 Accounts quota-estimation UI: include non-Claude auths; do not default Grok rows to Claude `pro`/`max*`; no cross-write of Claude plans
- [x] 3.4 Request Logs Account cell regression tests: no Claude/Grok qualifier for either provider
- [x] 3.5 Update Claude-only Settings/Accounts copy (`claude-sidecar-settings`, routing empty state, synthetic detail) to multi-provider-accurate wording; tab name stays CLIProxyAPI
- [x] 3.6 Document shared effort override applies to all CLIProxyAPI upstreams (help text), without claiming Grok honors it identically

## 4. Phase 1 — Tests and validation

- [x] 4.1 Invert/update fixtures that currently expect non-Claude auth files to be dropped (e.g. exceeded fixture `openai`/future `xai` retained)
- [x] 4.2 Backend tests: mixed Claude+xAI snapshot + routing list; pause/priority by `name`; poller OAuth gate; estimate window respect; parent aggregate null when mixed
- [x] 4.3 Backend tests: correlation prefers matching provider under two in-window events
- [x] 4.4 Frontend tests: routing provider labels; conditional bars; estimation defaults; request-log Account labels
- [x] 4.5 `openspec validate cliproxy-multi-provider-auth --strict` green after any spike-driven spec edits

## 5. Phase 2 — Grok routing and catalog honesty

- [ ] 5.1 Verify/configure CLIProxyAPI prefixes/full-models for Grok ids; seed defaults only if uniqueness-safe per spike 1.5
- [x] 5.2 Chat-completions tests: Grok full-model + prefix dispatch via existing sidecar path; unmatched `grok-*` does not force sidecar; shared effort override still applied
- [x] 5.3 Fix `dashboard/api.py` discovered-model labeling loop (no `Claude:` for non-Claude)
- [x] 5.4 Fix `/v1/models` `owned_by` for non-Claude CLIProxyAPI models (not `anthropic`)
- [x] 5.5 Cost path: ensure Anthropic pricing is not applied to Grok ids; optional Grok price rows; else `NULL`
- [ ] 5.6 Update operator docs in `context.md` with verified priority direction + family-selection findings + setup steps

## 6. Phase 3 — Live Grok quota enrichment (optional)

- [ ] 6.1 Only if spike found a stable live usage source: implement xAI adapter live windows
- [ ] 6.2 Prefer live % over manual estimates when both exist (mirror Claude OAuth preference)
- [ ] 6.3 If no stable source: mark Phase 3 cancelled/deferred; keep manual plans

## 7. Apply readiness / live ops

- [ ] 7.1 Do **not** restart `codex-lb` until operator confirms a safe window
- [ ] 7.2 After deploy: verify existing Claude cards/OAuth/pause/priority still correct before relying on Grok
- [ ] 7.3 Verify one Grok path: routing row, card windows/manual plan, request log Account `CLIProxyAPI: <email>`, model id, catalog label not Claude
- [ ] 7.4 Leave `claude_sidecar_*` → `cliproxy_*` rename out of this implementation PR
