## Context

`nohj.dev` already exposes codex-lb under `/codex`, and codex-lb stores its dashboard password session in an HTTP-only cookie scoped to `/`. OmniRoute currently runs locally on port `20128` and exposes both a dashboard and `/v1` API from that same origin.

## Goals / Non-Goals

**Goals:**

- Expose OmniRoute under `https://nohj.dev/omni`.
- Require an active codex-lb dashboard session before proxying `/omni`.
- Add an authenticated codex-lb dashboard navigation link that opens `/omni`.

**Non-Goals:**

- Do not embed the OmniRoute UI inside codex-lb.
- Do not change codex-lb request routing or account selection.
- Do not make codex-lb responsible for starting or supervising the OmniRoute process.

## Decisions

- Validate `/omni` access at the `nohj.dev` reverse proxy by forwarding the incoming cookie to codex-lb's dashboard session endpoint and requiring an authenticated response. This keeps the codex-lb password session as the source of truth and avoids duplicating session decryption outside codex-lb.
- Strip the `/omni` prefix when proxying to OmniRoute, matching the existing `/codex` prefix proxy pattern. OmniRoute can continue serving as though it is mounted at `/`.
- Render the OmniRoute affordance as an external navigation action from the codex-lb header. The dashboard link is visible only after codex-lb authentication because it is inside the existing AuthGate.

## Risks / Trade-offs

- Direct `/omni` requests depend on codex-lb being reachable for session validation. If codex-lb is down, `/omni` fails closed with an auth failure instead of exposing OmniRoute.
- If OmniRoute emits absolute root-relative asset URLs, the prefix proxy may need additional rewrite support. The initial implementation follows the existing codex-lb proxy pattern and can be extended if a concrete asset path issue appears.
