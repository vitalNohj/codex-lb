# Tasks

## 1. Backend

- [x] 1.1 Read `routing.session-affinity` from CLIProxyAPI `GET /v0/management/config` and write it by editing only that line in `config.yaml`.
- [x] 1.2 Add `sessionAffinity` to the routing response and `PUT /api/claude-sidecar/routing/session-affinity`.
- [x] 1.3 Tests: missing flag reads false; true reads true; the YAML upload keeps `session-affinity-ttl`; a body without `sessionAffinity` is rejected.

## 2. Frontend

- [x] 2.1 Add one Session affinity switch above the account list on the Accounts Claude detail, and one next to Routing strategy in Settings.
- [x] 2.2 Tests: one switch for several accounts; turning it on PUTs `sessionAffinity=true`; a live true value shows on.

## 3. Validation

- [x] 3.1 `openspec validate add-cliproxy-session-affinity-toggle --strict`.
- [x] 3.2 Targeted backend pytest and frontend vitest.
