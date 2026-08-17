## Purpose

Operator request logs should say **cooldown**, not **no auth available**, when CLIProxyAPI has parked Claude auths after overload/rate-limit. Client retry behavior stays the same.

## Non-goals

- Changing CLIProxyAPI cooldown duration or `disable-cooling`
- Remapping the harness-facing error
- Waiting out cooldown in codex-lb
- Relabeling Anthropic `Overloaded` itself (that string is already accurate)

## Example

Sidecar: `auth_unavailable: no auth available (providers=claude, model=claude-opus-5); check Claude auth/key session and cooldown state via /v0/management/auth-files`

Request log:

- `error_code`: `claude_sidecar_cooldown`
- `error_message`: `Claude sidecar cooldown for cc/claude-opus-5`
- `failure_detail`: original sidecar string

Client still sees the sidecar `auth_unavailable` envelope.

## Related

- CLIProxyAPI conductor cools 408/5xx for ~1 minute, then 503s with `auth_unavailable`
- `remap-sidecar-upstream-auth-errors` remaps **client** 401/403; this change is log-only and the opposite direction (keep client raw, clarify logs)
