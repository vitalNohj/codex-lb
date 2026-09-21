## Why

The dashboard Accounts section can hide Codex, CLIProxy, OpenRouter, NVIDIA, OrcaRouter, and OpenAI-compat accounts. OpenCode Go is rendered as a synthetic account with `provider: "opencode_go"`, but that provider is not a filter key, so the card stays on screen.

## What Changes

- Add an `opencode_go` account-type visibility key labeled `OpenCode Go`.
- Classify synthetic accounts with `provider: "opencode_go"` under that key so turning the toggle off removes them from the Accounts cards and list.
- Default the key to visible, including when hydrating a preference saved before the key existed.

## Capabilities

### New Capabilities

- none

### Modified Capabilities

- `frontend-architecture`: the dashboard account-type filter MUST include OpenCode Go

## Impact

- Frontend only: dashboard account-type preferences, the filter toggle, and `accountTypeKey`.
- No API, schema, or migration change. Existing localStorage preferences gain the new key on the next load.
