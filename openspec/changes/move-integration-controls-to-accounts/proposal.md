## Why

Integration management is split awkwardly across the dashboard. The Settings page owns manual connection testing and CLIProxyAPI quota estimation, even though those controls are most useful while looking at the corresponding synthetic account in the Accounts tab. The Accounts synthetic items also repeat the provider name as a badge (`CLIProxyAPI`, `OpenRouter`, `OmniRoute`) even though the account title already names the provider, mirroring the duplicate-badge cleanup already done on the dashboard account cards.

## What Changes

- Remove the duplicated sidecar-type badge from synthetic account list items and synthetic account detail headers, since the account title already identifies CLIProxyAPI, OpenRouter, or OmniRoute.
- Add a manual `Test connection` control to each synthetic integration account detail panel (CLIProxyAPI, OpenRouter, OmniRoute) and surface the integration connection status (status, base URL, last checked, health message) in the Accounts tab.
- Remove the manual `Test connection` buttons from the Settings integration sections.
- Make each Settings integration `Save` button persist settings first and then automatically run the matching connection test; toggling Enable or clearing an API key MUST NOT auto-test.
- Move CLIProxyAPI quota estimation editing out of Settings and into the CLIProxyAPI synthetic account detail panel. OpenRouter and OmniRoute do not gain quota-estimation controls.

## Capabilities

### New Capabilities

- None.

### Modified Capabilities

- `frontend-architecture`: The Accounts page synthetic integration account presentation contract and the Settings page integration save/test contract.

## Impact

- Affects Accounts UI (`account-list-item.tsx`, `account-detail.tsx`, new `synthetic-account-detail.tsx`, new `claude-sidecar-quota-estimation.tsx`).
- Affects Settings integration sections (`claude-sidecar-settings.tsx`, `openrouter-sidecar-settings.tsx`, `omniroute-sidecar-settings.tsx`) and the settings hooks (`use-settings.ts`).
- Adds no new dependencies, database schema changes, or public API contracts. Reuses existing `/api/{claude,openrouter,omniroute}-sidecar/test` endpoints and existing account summary fields.
