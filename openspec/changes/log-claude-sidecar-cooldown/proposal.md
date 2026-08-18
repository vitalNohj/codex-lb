## Why

CLIProxyAPI cooldown after Anthropic `Overloaded` / 429 is working as designed: it parks cooled Claude auths and later requests fail fast. Two operator bugs follow from that 503:

1. Request logs copy `auth_unavailable: no auth available`, which reads like missing credentials.
2. BYOK clients such as Kodus record **every** HTTP error (`ByokErrorCounter`, threshold 5 in 15 minutes) and email owners. A review fan-out during the ~60s cool window is 5+ fail-fast 503s, so the email fires on cooldown, not on a real outage.

Harness retries do not help Kodus: it counts each failed `doGenerate()` before retry/fallback.

## What Changes

- When a Claude sidecar error is `auth_unavailable` / `no auth available`, retry the sidecar call for up to ~75s (just past CLIProxyAPI's ~60s cool). If it succeeds, the client sees one success. If the budget expires, emit **one** client error with the original sidecar envelope.
- Persist exhausted cooldown as `error_code=claude_sidecar_cooldown` and an error message that names cooldown and the model; keep the original sidecar string on `failure_detail`.
- Do not retry Anthropic `Overloaded` / other sidecar errors. Do not change CLIProxyAPI `disable-cooling`.

## Capabilities

### New Capabilities

<!-- none -->

### Modified Capabilities

- `proxy-runtime-observability`: Claude sidecar cooldown 503s must be waited out before the client sees an error, and exhausted cooldown must be labeled as cooldown in request logs.

## Impact

- Request Logs Error Code / Error Message for exhausted cooldown.
- Claude sidecar dispatch: retry loop on non-stream and stream chat completions.
- Kodus/BYOK: cooldown bursts no longer count as 5 LLM errors. A real `Overloaded` still surfaces as a client error (one per request that actually hit it).
- Held requests may last ~75s extra during cooldown. SSE keepalives still fire on the stream path.
