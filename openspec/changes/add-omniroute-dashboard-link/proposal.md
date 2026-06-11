## Why

Operators currently run OmniRoute manually and must know its local dashboard URL. Since codex-lb is already exposed through `nohj.dev` and protected by the dashboard password, the dashboard should offer an authenticated path to the OmniRoute dashboard under the same public domain.

## What Changes

- Add an authenticated Codex LB dashboard navigation affordance that opens the external OmniRoute dashboard at `/omni`.
- Keep OmniRoute hosted outside codex-lb; the reverse proxy and access check are implemented by the surrounding `nohj.dev` server.
- Avoid changing codex-lb API routing, account routing, or OpenAI-compatible proxy behavior.

## Capabilities

### New Capabilities

- None.

### Modified Capabilities

- `frontend-architecture`: The dashboard navigation contract will include an OmniRoute link available after dashboard authentication.

## Impact

- Affects codex-lb dashboard header navigation.
- Affects `nohj.dev` Express reverse proxy configuration for `/omni`.
- Adds no new codex-lb dependencies, database schema changes, or public API contracts.
