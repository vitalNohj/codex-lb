# Design: CLIProxyAPI weighted-round-robin in the dashboard

## Decision

Extend the existing CLIProxyAPI strategy enum and wire map. Do not add weight inputs.

Dashboard values stay snake_case (`weighted_round_robin`). CLIProxyAPI wire value is `weighted-round-robin`. The existing `_STRATEGY_TO_WIRE` / `_WIRE_TO_STRATEGY` pair in `ClaudeSidecarService` is the only mapping. Unknown live strategies still become `strategy=null`.

## Why not weight UI

WRR without explicit weights is valid (every auth defaults to 1 → even mix). Operators already set `weight` on auth JSON or via CLIProxyAPI `PATCH /v0/management/auth-files/fields`. A weight editor is a separate change.

## Why not native Codex strategies

`capacity_weighted` and friends still apply only to Codex accounts. This dropdown talks to CLIProxyAPI's Management API, not `LoadBalancer`.

## Copy

The routing help line must mention that WRR mixes by per-auth `weight` inside the top priority group, and that omitted weights default to 1.

## Risks

- Choosing WRR with default weights looks like round-robin until weights are set. Copy covers that.
- CLIProxyAPI older than 7.2.135 may reject the wire value. The operator already runs 7.2.135+; surface the upstream error the same way as other strategy PUTs.
