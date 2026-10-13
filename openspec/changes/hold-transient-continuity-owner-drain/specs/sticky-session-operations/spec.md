# sticky-session-operations (delta)

## ADDED Requirements

### Requirement: Transiently drained required owners get a bounded hold before fail-closed

When a required continuity owner (previous-response owner, hard turn-state owner, file-pin owner, or another required owner source) fails account selection, the service MUST classify why the owner is unavailable before surfacing the fail-closed continuity error. If the owner is unavailable only because it is transiently drained or probing — bounded error backoff after repeated transient upstream errors, or the DRAINING/PROBING health tier — the service MUST hold the request for a short bounded wait (default 10 seconds, configurable via `proxy_continuity_owner_hold_seconds`, 0 disables) re-checking the owner selection during the hold. If the owner becomes selectable during the hold, the service MUST proceed on that same owner and MUST NOT reroute the continuation to a different account. If the hold expires, the service MUST respond with HTTP 503 plus a `Retry-After` header carrying the same `previous_response_owner_unavailable` error body and code instead of the instant 502. While waiting, the request MUST NOT hold an account lease, stream slot, or response-create gate, and client disconnect/cancel MUST propagate immediately. Permanent unavailability (owner removed, deactivated, paused, re-auth required, rate-limited, quota-exhausted, in cooldown, outside the eligible policy, or lookup miss) MUST keep the existing instant fail-closed behavior without any hold. The stable `previous_response_owner_unavailable` error code MUST be identical on both the instant-502 and hold-expired-503 paths so clients cannot distinguish the two by error identity.

#### Scenario: Drained owner recovers within the hold

- **GIVEN** a continuity-bound follow-up requires a previous-response owner account
- **AND** the owner is unavailable only because repeated transient upstream errors placed it in bounded error backoff
- **WHEN** the owner's error backoff expires during the bounded hold
- **THEN** the follow-up is dispatched to that same owner account
- **AND** the client receives the normal successful response instead of a continuity failure

#### Scenario: Drained owner stays down past the hold

- **GIVEN** a continuity-bound follow-up requires a previous-response owner account
- **AND** the owner remains transiently drained for the whole bounded hold
- **WHEN** the hold expires
- **THEN** the service responds with HTTP 503 and a `Retry-After` header
- **AND** the error body carries the stable `previous_response_owner_unavailable` code
- **AND** the service does not reroute the follow-up to a different account

#### Scenario: Permanently unavailable owner keeps instant fail-closed

- **GIVEN** a continuity-bound follow-up requires a previous-response owner account
- **AND** the owner is removed from the pool, deactivated, paused, re-auth required, rate-limited, quota-exhausted, or outside the eligible policy
- **WHEN** account selection fails
- **THEN** the service fails closed immediately with the existing continuity error
- **AND** no bounded hold is started

#### Scenario: Client cancels while the hold is waiting

- **GIVEN** a continuity-bound follow-up is waiting inside the bounded hold for a transiently drained owner
- **WHEN** the client disconnects or cancels the request
- **THEN** the wait ends immediately with the request cancelled
- **AND** no account lease, stream slot, or response-create gate remains held for the cancelled request