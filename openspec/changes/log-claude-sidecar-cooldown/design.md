## Context

CLIProxyAPI treats transient 502/`Overloaded` (and 429) as credential cooldown (~1 minute). Follow-up calls return HTTP 503 with `auth_unavailable: no auth available (providers=claude, model=…)`. codex-lb stores that string as `claude_sidecar_error`. Dashboard Error Code/Message then look like a missing-provider outage.

## Decisions

1. Remap **request-log fields only**. Client JSON/SSE stays the raw sidecar envelope so harness retries keep their current matching.
2. Detect cooldown via `auth_unavailable` or `no auth available` in the sidecar message (CLIProxyAPI's current phrasing). Do not match generic `unavailable`.
3. Persist `error_code=claude_sidecar_cooldown` and `error_message=Claude sidecar cooldown for <model>` using the already-resolved request model (including `cc/` prefixes).
4. Store the original sidecar message in `failure_detail`. Do not invent a new column.
5. Do not change CLIProxyAPI `disable-cooling` / `max-retry-interval`. Cooldown stays.

## Risks and Mitigations

- **True empty auth pool** (no auth files at all) uses the same sidecar string → Mitigation: still a "no usable auth right now" state; cooldown wording is the common live case. `failure_detail` keeps the raw text.
- **Sidecar wording drift** → Mitigation: match both `auth_unavailable` and `no auth available`; expand if a new canonical phrase appears.

## Verification

- Unit-test the log-field mapper.
- Integration-test non-stream and stream Claude sidecar paths write cooldown code/message and leave the client envelope as `auth_unavailable`.
- `openspec validate log-claude-sidecar-cooldown --strict`.
