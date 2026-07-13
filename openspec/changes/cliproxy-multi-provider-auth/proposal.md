# CLIProxyAPI Multi-Provider Auth Surface

## Why

CLIProxyAPI is already a multi-upstream credential proxy (`-claude-login`, `-xai-login`, and other provider logins), but codex-lb's observation and control surfaces still filter and shape CLIProxyAPI auth files as Claude-only. Operators who add Grok/xAI (and later Kimi / other CLIProxyAPI providers) get working transport only if they hand-configure prefixes, while Dashboard cards, Settings routing/priority/pause lists, OAuth quota bars, and auth-plan estimation remain Claude-scoped or misleading.

This change reframes the CLIProxyAPI integration as a **multi-provider auth surface** with provider-specific quota adapters, without splitting into a second Settings integration or renaming the live `claude_sidecar_*` persistence yet.

## What Changes

- Treat CLIProxyAPI auth files as a **single global credential pool**: one routing strategy (`round_robin` / `fill_first`) and one priority/pause list spanning Claude, Grok/xAI, and future CLIProxyAPI providers.
- Introduce a **provider-adapter registry first**, then widen auth ingestion so non-Claude auth files appear in quota snapshots, routing APIs, Dashboard cards/list rows, and Settings routing controls. Widening without adapters is explicitly forbidden (it would call Anthropic OAuth and invent Claude 5h/weekly bars for Grok).
- Expose a concrete observation contract on auth/routing APIs: normalized `provider`, `quota_windows`, and `supports_manual_plan` so frontend bars and estimation UI cannot guess.
- Keep Dashboard CLIProxyAPI auth cards visually aligned with current Codex-parity chrome: header, provider-aware subtitle, quota widget driven by `quota_windows` (weekly when known; 5h only when declared), reasoning-effort override slot, Details + Pause/Resume. No credits row. No warm-up controls.
- Keep Request Logs Account labeling as `CLIProxyAPI: <account email/label>` (or bare `CLIProxyAPI` on correlation miss). **Do not** insert `Claude`/`Grok` into the Account cell.
- Prefer same-provider usage-queue correlation when multiple events fall in the 30s window (reduces mixed-traffic mislabel risk).
- Route Grok/xAI through the existing CLIProxyAPI sidecar entry (prefixes / full-models). Fix Claude-hardcoded model catalog labels and `owned_by: anthropic` for non-Claude CLIProxyAPI models.
- Preserve `source="claude_sidecar"` request-log source key and internal sidecar resolver id `"claude"` (rename deferred).

## Non-Goals

- Do **not** rename modules/settings/API paths from `claude_sidecar` → `cliproxy` in this change.
- Do **not** add a second External Integrations tab for the same CLIProxyAPI instance.
- Do **not** put provider names into Request Logs Account cells.
- Do **not** manage CLIProxyAPI process lifecycle or OAuth login UX from codex-lb.
- Do **not** change native Codex LB, OpenRouter, OmniRoute, or Ollama.
- Do **not** assume Anthropic 5h/weekly semantics for every provider.
- Do **not** add per-upstream reasoning-effort overrides in this change (one shared `claude_sidecar_default_reasoning_effort` remains).
- Do **not** invent CLIProxyAPI per-provider routing strategies in codex-lb.

## Locked Decisions (from exploration)

1. **Scope = B (generic multi-provider shell)** — Grok/xAI first; must not hard-block Kimi/others.
2. **Architecture = Option 2 (provider plugins)** — one CLIProxyAPI integration + observation adapters.
3. **Credential selection = one global pool** — one strategy + one priority/pause namespace across providers (UI labeled by provider).
4. **Quota widget** — same card chrome; weekly when available; 5h only if declared; else Claude-style manual auth-plan inputs.
5. **Request log Account** — `CLIProxyAPI: <account>`; no Claude/Grok qualifier.

## Capabilities

### New Capabilities

- None.

### Modified Capabilities

- `dashboard-sidecar-management`: Multi-provider ingestion, adapter-gated OAuth/estimates, routing pool, auth-plan compatibility, correlation preference, Grok routing via existing integration.
- `frontend-architecture`: Routing UI provider labels; adapter-driven quota bars; manual estimation for non-Claude; Request Logs Account non-regression; copy cleanup.
- `chat-completions-compat`: CLIProxyAPI-matched Grok models dispatch through existing sidecar path when configured.
- `model-catalog-compat`: Non-Claude CLIProxyAPI models must not be labeled/owned as Claude/Anthropic on `/v1/models` or dashboard model lists.

## Impact

- Backend (must touch): `quota.py`, `quota_poller.py`, `oauth_usage.py` call sites, `usage_estimates.py`, `service.py` routing builders, `schemas.py` (`ClaudeSidecarRoutingAccount`, quota responses), `accounts/schemas.py` (`SidecarAuthAccount`), `sidecar_summary.py` (parent aggregate), `settings/schemas.py` + auth-plan parse/dump (optional `provider` on plan rows), `request_logs/repository.py` correlation, `dashboard/api.py` model labeling, `proxy/api.py` `/v1/models` `owned_by`, optional `pricing.py`.
- Frontend (must touch): `ClaudeAuthCard` / `ClaudeAuthListRow` / `SyntheticAccountDetail` conditional bars; Settings routing list provider column; quota-estimation UI for non-Claude; Request Logs Account regression tests; Claude-only copy in `claude-sidecar-settings.tsx` / routing empty states.
- Tests/fixtures that currently assert non-Claude auth files are dropped must be inverted for multi-provider retention.
- Ops: no restart for this OpenSpec revision; implementation later needs operator-approved `codex-lb` restart. Phase 0 spike may restart/use CLIProxyAPI only.
- Auth-plan persistence stays a JSON **array** (additive optional `provider` field); no object-map rewrite.
