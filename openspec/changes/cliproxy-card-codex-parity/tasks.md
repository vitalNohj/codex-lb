# Tasks

## 1. Dashboard card view
- [x] 1.1 Add a per-auth `ClaudeAuthCard` in `account-card.tsx` mirroring the native Codex card layout (header, 5h/weekly quota bars, reasoning-effort override in the warm-up slot, Details + Pause/Resume).
- [x] 1.2 Expand each CLIProxyAPI (Claude sidecar) synthetic account with `sidecarAuths` into one `ClaudeAuthCard` per auth in `account-cards.tsx`.
- [x] 1.3 Keep the fallback (`Claude Usage`, no auths) and OpenRouter/OmniRoute synthetic card rendering unchanged.

## 1b. Credential provider label
- [x] 1b.1 Thread a `provider` field through `SidecarAuthQuota` (parse + JSON round-trip) in `quota.py`.
- [x] 1b.2 Add `provider` to `SidecarAuthAccount` (`schemas.py`) and populate it in `sidecar_summary.py`.
- [x] 1b.3 Add `provider` to the frontend `SidecarAuthAccountSchema` and render the subtitle as `<plan> | <provider>` (`Claude` when known, else `CLIProxyAPI`).

## 1c. Dashboard list (tiered) view
- [x] 1c.1 Add a `compact` variant to `SidecarEffortSelect` for the narrow warm-up column.
- [x] 1c.2 Expand each CLIProxyAPI (Claude sidecar) synthetic account with `sidecarAuths` into one `ClaudeAuthListRow` per auth in `account-list.tsx` (label + provider subtitle, status, plan, 5h/weekly quota, effort override, `-` credits, Details + Pause/Resume).

## 2. Tests
- [x] 2.1 Update `account-card.test.tsx` for the per-auth codex-style CLIProxyAPI card (layout, pause/resume, privacy blur, no credits/warm-up rows).
- [x] 2.2 Add an `account-cards.test.tsx` case asserting a Claude sidecar account expands into one card per auth.
- [x] 2.3 Add an `account-list.test.tsx` case asserting a Claude sidecar account expands into one list row per auth.

## 3. Validation
- [x] 3.1 `npx vitest run` for the affected dashboard tests.
- [x] 3.2 `openspec validate cliproxy-card-codex-parity --strict`.
