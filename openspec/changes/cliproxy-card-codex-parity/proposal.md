## Why

The CLIProxyAPI (Claude sidecar) synthetic dashboard card renders differently from native Codex account cards: one combined card holding stacked per-auth usage boxes, a shared reasoning-effort override, and only a Details action. Now that each CLIProxyAPI auth account supports Pause/Resume, the cards can look almost identical to Codex cards. The only structural difference is that CLIProxyAPI has no warm-up controls; that slot is instead occupied by the per-provider reasoning-effort override.

## What Changes

- Render each CLIProxyAPI (Claude sidecar) auth account as its own dashboard account card, matching the native Codex card layout: header (title + plan/usage-source subtitle + status badge), 5h and weekly quota bars, and a Details + Pause/Resume action row.
- Place the reasoning-effort override in the card slot where native cards render warm-up controls.
- Label the credential provider in each auth card subtitle (`<plan> | <provider>`): `Claude` when the auth account's provider is known to be Claude, else `CLIProxyAPI`. The provider is threaded from the CLIProxyAPI auth file through the quota snapshot and synthetic auth summary.
- CLIProxyAPI auth cards do NOT render a credits row or warm-up controls.
- Pause/Resume on a CLIProxyAPI auth card writes the per-account pause setting for that auth account.
- Apply the same per-auth split to the dashboard list (tiered) view: each CLIProxyAPI auth account renders its own list row (label + provider subtitle, status, plan, 5h/weekly quota, reasoning-effort override in the warm-up column, `-` credits, Details + Pause/Resume actions).
- OpenRouter and OmniRoute synthetic cards/rows are unchanged by this change.

## Capabilities

### New Capabilities

- None.

### Modified Capabilities

- `frontend-architecture`: The CLI Proxy API synthetic account-card presentation contract on the dashboard card view.

## Impact

- Affects the codex-lb dashboard account cards (`account-cards.tsx`, `account-card.tsx`) and the account list view (`account-list.tsx`).
- Adds a `compact` variant to `SidecarEffortSelect` so the reasoning-effort override fits the list's warm-up column.
- Threads a credential `provider` field from `quota.py` (`SidecarAuthQuota`) through `sidecar_summary.py` and `schemas.py` (`SidecarAuthAccount`) to the frontend `SidecarAuthAccount` schema.
- Adds no new dependencies, database schema changes, or public API contracts.
