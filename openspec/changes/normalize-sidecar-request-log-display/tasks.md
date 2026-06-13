## 1. Recent requests table

- [x] 1.1 Remove the sidecar-specific badge rendered under the Model cell.
- [x] 1.2 Render sidecar Transport cells through the existing standard transport label path.
- [x] 1.3 Render request-details Transport through the existing standard transport label path.
- [x] 1.4 Render sidecar Account cells with `CLIProxyAPI`, `OpenRouter`, and `OmniRoute` provider labels.

## 2. Request-log API metadata

- [x] 2.1 Add optional request-log response metadata for Claude sidecar auth identity.
- [x] 2.2 Populate Claude sidecar auth identity from matching sidecar usage events when available.

## 3. Tests and verification

- [x] 3.1 Update the Recent Requests table test to assert sidecar rows do not show model sidecar badges or `Sidecar HTTP`.
- [x] 3.2 Update tests for sidecar Account labels and optional Claude auth identity.
- [x] 3.3 Run focused backend and frontend tests.
- [x] 3.4 Validate the OpenSpec change with `--strict`.
