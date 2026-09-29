# Add CLIProxyAPI session affinity toggle

## Why

CLIProxyAPI session affinity is a global routing flag (`routing.session-affinity`). Operators can already set the routing strategy from the dashboard, but turning affinity on or off still means editing CLIProxyAPI config by hand. The control is not per account.

## What Changes

- Read and write the global CLIProxyAPI session-affinity flag from the dashboard routing API.
- Show one Session affinity switch in the global part of the Accounts Claude detail, above the per-account list.
- Show the same switch once in the Settings CLIProxyAPI routing panel, next to Routing strategy.
- Do not add the switch to each account row. Do not add TTL, subagent, or weight controls.

## Capabilities

### New Capabilities

- None

### Modified Capabilities

- `dashboard-sidecar-management`: routing GET/PUT exposes the global session-affinity flag and maps it to CLIProxyAPI `routing.session-affinity`.
- `frontend-architecture`: one global Session affinity switch on the Accounts Claude detail and in the CLIProxyAPI routing panel.

## Impact

- Affected backend: `app/core/clients/claude_sidecar.py`, `app/modules/claude_sidecar/api.py`, `app/modules/claude_sidecar/service.py`, `app/modules/claude_sidecar/schemas.py`
- Affected frontend: Accounts Claude detail, CLIProxyAPI routing panel, routing schema and hooks
- No migrations. codex-lb still does not select Claude accounts. CLIProxyAPI keeps that selection, including affinity.
