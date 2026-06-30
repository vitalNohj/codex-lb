## 1. Backend Management API client

- [x] 1.1 Add `get_routing_strategy`, `set_routing_strategy`, and `patch_auth_file_priority` to `ClaudeSidecarClient`.
- [x] 1.2 Extend the unit-test fake HTTP session with `put` and `patch` helpers.
- [x] 1.3 Add unit tests for routing strategy reads, strategy updates, priority patches, and upstream errors.

## 2. Backend service and dashboard API

- [x] 2.1 Add routing request/response schemas for strategy, status, accounts, and priority updates.
- [x] 2.2 Add Claude sidecar service methods that guard disabled/not-configured states, map strategy names, read live auth-file priorities, and forward updates.
- [x] 2.3 Add `GET /api/claude-sidecar/routing`, `PUT /api/claude-sidecar/routing/strategy`, and `PUT /api/claude-sidecar/routing/priority` routes.
- [x] 2.4 Add integration tests for disabled, not-configured, healthy, invalid strategy, strategy update, and priority update cases.

## 3. Frontend data layer

- [x] 3.1 Add Zod schemas and types for CLIProxyAPI routing state.
- [x] 3.2 Add frontend API functions for reading routing state and updating strategy/account priority.
- [x] 3.3 Extend `useClaudeSidecar` with a management-key-gated routing query and update mutations.

## 4. Frontend UI

- [x] 4.1 Add a presentational routing section to the shared sidecar integration card.
- [x] 4.2 Render the routing section only in the CLIProxyAPI tab when a management key is configured.
- [x] 4.3 Commit priority changes on blur or Enter and strategy changes immediately.
- [x] 4.4 Add frontend tests for visible routing state, hidden controls without a management key, strategy update, and priority update.

## 5. Validation

- [x] 5.1 Run `openspec validate add-cliproxy-routing-controls --strict`.
- [x] 5.2 Run targeted backend pytest for the Claude sidecar client and dashboard API.
- [x] 5.3 Run targeted frontend vitest for the settings components.
- [x] 5.4 Check lints on edited source files.
