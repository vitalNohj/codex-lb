## Purpose

Operator request logs should say **cooldown**, not **no auth available**, when CLIProxyAPI has parked Claude auths after overload/rate-limit. BYOK clients (Kodus) must not see a burst of fail-fast 503s during that window.

## Non-goals

- Changing CLIProxyAPI cooldown duration or `disable-cooling`
- Relabeling Anthropic `Overloaded` itself (that string is already accurate)
- Changing Kodus notification thresholds

## Example

Sidecar: `auth_unavailable: no auth available (providers=claude, model=claude-opus-5); check Claude auth/key session and cooldown state via /v0/management/auth-files`

During cool (~60s): proxy retries internally. Client gets 200 if auth returns. One request-log row, status success.

If still unavailable after 75s:

- `error_code`: `claude_sidecar_cooldown`
- `error_message`: `Claude sidecar cooldown for cc/claude-opus-5`
- `failure_detail`: original sidecar string
- Client still sees the sidecar `auth_unavailable` envelope **once**

## Related

- CLIProxyAPI conductor cools 408/5xx for ~1 minute, then 503s with `auth_unavailable`
- Kodus `ByokErrorCounter`: 5 errors / 15 min → email + in-app; sampleError is the latest message
- `remap-sidecar-upstream-auth-errors` remaps **client** 401/403
