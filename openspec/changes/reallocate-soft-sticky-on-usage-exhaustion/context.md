# Context

A Cursor `POST /v1/chat/completions` first turn with prompt-cache stickiness selected an
exhausted Plus Codex seat. Upstream returned `usage_limit_reached` ("The usage limit has
been reached") before any tokens. `failover_decision` chose `failover_next`, then the
retry still required that same account as the dispatched-payload owner (`excluded=True`,
`reallocate_sticky=False`) and surfaced the original 429. Resume repeated the same pin.

`usage_limit_reached` is classified as `rate_limit` (30s floor, usage snapshots stay
advisory). Soft prompt-cache preserve-on-fallback is correct for short
`rate_limit_exceeded` blips and must stay. This change only rebinds after the
usage-exhaustion family, and only when the request is not hard-owned.
