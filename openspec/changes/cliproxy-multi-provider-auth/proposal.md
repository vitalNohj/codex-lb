# CLIProxyAPI Multi-Provider Auth Surface

## Why

CLIProxyAPI is already a multi-upstream credential proxy (`-claude-login`, `-xai-login`, and other provider logins), but codex-lb's observation and control surfaces still filter and shape CLIProxyAPI auth files as Claude-only. Operators who add Grok/xAI (and later Kimi / other CLIProxyAPI providers) get working transport only if they hand-configure prefixes, while Dashboard cards, Settings routing/priority/pause lists, OAuth quota bars, and auth-plan estimation remain Claude-scoped or misleading.

This change reframes the CLIProxyAPI integration as a **multi-provider auth surface** with provider-specific quota adapters, without splitting into a second Settings integration or renaming the live `claude_sidecar_*` persistence yet.

## What Changes

- Treat CLIProxyAPI auth files as a **single global credential pool**: one routing strategy (`round_robin` / `fill_first`) and one priority/pause list spanning Claude, Grok/xAI, and future CLIProxyAPI providers.
- Widen auth ingestion so non-Claude auth files appear in quota snapshots, routing APIs, Dashboard Cards/list rows, and Settings routing controls (no longer filtered to `provider=="claude"` / `type=="claude"`).
- Introduce a **provider-plugin (adapter) pattern** for observation: Claude keeps Anthropic OAuth usage + existing plan presets; Grok/xAI (and future providers) plug in their own usage derivation when available, otherwise fall back to **manual auth-plan / quota-estimation inputs** in the same shape operators already use for Claude accounts.
- Keep Dashboard CLIProxyAPI auth cards visually aligned with current Codex-parity cards: header, quota widget (weekly required when known; 5h optional when the provider exposes it), reasoning-effort override slot, Details + Pause/Resume. No credits row. No warm-up controls.
- Keep Request Logs Account labeling as `CLIProxyAPI: <account email/label>` (or bare `CLIProxyAPI` on correlation miss). **Do not** insert `Claude`/`Grok` into the Account cell; the Model column remains the primary provider signal.
- Add operator-facing routing for Grok/xAI through the existing CLIProxyAPI sidecar entry (prefixes / full-models / model-catalog labeling), without creating a separate OmniRoute-style integration card for the same CLIProxyAPI base URL.
- Preserve existing Claude OAuth %, pause/priority Management API wiring, usage-queue ingestion, and `source="claude_sidecar"` request-log source key for this change (rename to `cliproxy_*` is explicitly deferred).

## Non-Goals

- Do **not** rename modules/settings/API paths from `claude_sidecar` → `cliproxy` in this change (deferred follow-up).
- Do **not** add a second External Integrations tab that points at the same CLIProxyAPI instance.
- Do **not** put provider names (`Claude`/`Grok`) into Request Logs Account cells.
- Do **not** manage CLIProxyAPI process lifecycle, OAuth browser login UX, or auth-file creation from codex-lb (operators still use `cli-proxy-api --xai-login` / `--claude-login`).
- Do **not** change native Codex load-balancing, OpenRouter, OmniRoute, or Ollama integrations.
- Do **not** assume Anthropic 5h/weekly semantics apply to every provider; adapters decide which windows exist.

## Locked Decisions (from exploration)

1. **Scope = B (generic multi-provider shell)** — Grok/xAI is the first non-Claude provider; design must not hard-block Kimi/others behind a Grok-only fork.
2. **Architecture = Option 2 (provider plugins)** — one CLIProxyAPI integration + per-provider observation adapters; not a bare filter-widen, not a full rename, not a duplicate integration card.
3. **Credential selection = one global pool** — CLIProxyAPI `fill-first` / `round-robin` + per-auth priority/pause apply across all auth files in one list (grouped/labeled by provider in UI, but one strategy and one priority namespace).
4. **Quota widget** — same card chrome; weekly when available; 5h only when the provider exposes it; if live limits cannot be derived, use Claude-style manual auth-plan / estimation inputs.
5. **Request log Account** — `CLIProxyAPI: <account>`; no Claude/Grok qualifier in the Account cell.

## Capabilities

### New Capabilities

- None. Multi-provider behavior extends the existing CLIProxyAPI sidecar management surface.

### Modified Capabilities

- `dashboard-sidecar-management`: Multi-provider auth ingestion, routing list membership, provider adapters for usage/quota estimation, pause/priority across all CLIProxyAPI auth files, Grok/xAI routing configuration through the existing CLIProxyAPI integration.
- `frontend-architecture`: Dashboard per-auth cards/list rows and Settings routing UI for multi-provider CLIProxyAPI auths; quota widget window presence per provider; Request Logs Account labeling stays provider-agnostic (`CLIProxyAPI: <account>`).
- `chat-completions-compat`: Ensure CLIProxyAPI-routed Grok/xAI (and future CLIProxyAPI provider) models continue to dispatch through the existing CLIProxyAPI sidecar path when prefixes/full-models match.
- `model-catalog-compat`: CLIProxyAPI-discovered / configured models MUST NOT be hard-labeled as Claude-only when the upstream provider is non-Claude.

## Impact

- Backend: `app/modules/claude_sidecar/` (quota parse/filter, service routing accounts, oauth usage, usage estimates, schemas/api), `app/modules/accounts/sidecar_summary.py`, `app/modules/proxy/claude_sidecar_dispatch.py` / `sidecar_routing.py` (prefix seeding / catalog labels only as needed), `app/core/usage/pricing.py` (optional Grok reference cost), request-log label helpers only if they currently inject provider into Account text.
- Frontend: CLIProxyAPI Settings card routing list, Dashboard `ClaudeAuthCard` / list rows (provider-aware quota windows + subtitle), Accounts quota-estimation panel for non-Claude auths, Request Logs Account cell (explicit non-regression).
- OpenSpec: change-level deltas under the capabilities above; change-level `context.md` for rationale/ops/spike notes.
- Ops: live `codex-lb` must not be restarted by this planning change; implementation later needs a coordinated restart window. Adding xAI auth files is an operator CLIProxyAPI action (`--xai-login`), independent of codex-lb deploys.
- **No** DB rename/migration required for the deferred `claude_sidecar_*` → `cliproxy_*` rename. Auth-plan JSON may gain per-provider keys if needed (additive, backward compatible).
