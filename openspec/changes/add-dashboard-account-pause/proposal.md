## Why

Operators can only pause a normal Codex account from the Accounts tab account
detail panel. From the Dashboard tab account cards, the only way to pause is to
click `Details`, navigate to the Accounts page, and pause there. This is an
unnecessary detour for a common operation, and a paused account is already
resumable directly from the Dashboard card.

## What Changes

- Add a direct `Pause` action to each normal (non-synthetic) Codex account card
  in the Dashboard Accounts section.
- The action toggles with the existing `Resume` action: pausable accounts show
  `Pause`, and paused accounts continue to show `Resume`.
- The action reuses the existing `POST /api/accounts/{account_id}/pause`
  mutation path, so account status and dashboard summaries refresh through the
  existing query invalidation.
- Synthetic/read-only sidecar cards (CLIProxyAPI, OpenRouter, OmniRoute) do not
  gain pause or resume controls.

## Capabilities

### Modified Capabilities

- `frontend-architecture`: Dashboard normal account cards expose a direct pause
  action that toggles with resume.

## Impact

- **Code**: dashboard account card component, dashboard page action wiring.
- **Tests**: dashboard account card rendering/click coverage for pause
  visibility, paused resume state, and sidecar exclusion.
