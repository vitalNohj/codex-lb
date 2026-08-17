## Why

CLIProxyAPI cooldown after Anthropic `Overloaded` / 429 is working as designed: it parks cooled Claude auths and later requests fail fast. The persisted request-log row currently copies the sidecar string `auth_unavailable: no auth available (providers=claude, model=…)`, which reads like missing credentials. Operators then think Claude auth is gone. It is cooldown.

Harnesses already retry; this change does not alter client envelopes or cooldown behavior.

## What Changes

- When a Claude sidecar error is `auth_unavailable` / `no auth available`, persist `error_code=claude_sidecar_cooldown` and an error message that names cooldown and the model.
- Keep the original sidecar message on `failure_detail` for triage.
- Leave the client-facing HTTP/SSE error unchanged.

## Capabilities

### New Capabilities

<!-- none -->

### Modified Capabilities

- `proxy-runtime-observability`: Claude sidecar cooldown failures must be labeled as cooldown in request logs, not as missing auth.

## Impact

- Request Logs Error Code / Error Message columns for this failure.
- Claude sidecar dispatch log writer only.
- No client retry/status change, no CLIProxyAPI cooldown change.
