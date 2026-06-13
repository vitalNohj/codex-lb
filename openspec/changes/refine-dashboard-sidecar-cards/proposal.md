## Why

The dashboard account list caps its scrollable viewport too tightly, so fewer than two full rows of account cards are visible before scrolling. The synthetic Claude/CLI Proxy API card is also noisy: it shows an aggregate "Claude usage" panel plus `Health`, `Quota`, `Models`, and `Requests` metadata rows, instead of focusing on per-account (per-auth) usage. Finally, the OpenRouter and OmniRoute synthetic cards render stale health and account states whenever an older health probe recorded `disabled` or a health probe has not succeeded, even when the sidecar is enabled and configured in settings, which misrepresents their operator-intended state.

## What Changes

- Increase the dashboard account-card two-row viewport so at least two full rows of cards are visible before scrolling.
- Rename the Claude synthetic account card to `CLI Proxy API` and render one compact, privacy-aware usage panel per sidecar auth account, headed by that auth's email (or name) plus `Usage`.
- Remove the Claude synthetic card's lower `Health`, `Quota`, `Models`, and `Requests` metadata rows.
- Remove model-count rows from the OpenRouter and OmniRoute dashboard cards; keep their health and request rows.
- Derive the OpenRouter and OmniRoute synthetic account status as `active` when the sidecar is enabled and configured, instead of `paused`, without hiding real disabled/missing-key states.
- Derive the OpenRouter and OmniRoute synthetic health from the same effective status rules as the settings health endpoint so stale `disabled` or `missing_api_key` probe values do not appear after the sidecar is re-enabled and configured.

## Capabilities

### New Capabilities

- None.

### Modified Capabilities

- `frontend-architecture`: The dashboard account-card viewport and synthetic sidecar account-card presentation contract.

## Impact

- Affects the codex-lb dashboard account cards (`account-cards.tsx`, `account-card.tsx`).
- Affects synthetic sidecar account summaries (`sidecar_summary.py`, `openrouter_sidecar_summary.py`, `omniroute_sidecar_summary.py`).
- Adds no new dependencies, database schema changes, or public API contracts.
