## ADDED Requirements

### Requirement: Shutdown ends a Claude chat stream with a retryable error
When process shutdown is committed and the drain has no more than half a second left, an in-flight Claude sidecar chat stream MUST yield one SSE error whose message is `503 service unavailable` and then end, before the connection is cancelled. A client disconnect while shutdown is not committed MUST NOT yield that error.

#### Scenario: Restart hands the open stream to the client

- **GIVEN** an in-flight Claude chat stream
- **AND** process shutdown is committed with at most half a second of drain left
- **WHEN** the stream wrapper waits on the next upstream chunk
- **THEN** the next yielded frame is the SSE error `503 service unavailable`
- **AND** the upstream iterator is closed

#### Scenario: An ordinary stream does not emit the shutdown error

- **GIVEN** an in-flight Claude chat stream
- **AND** process shutdown is not committed
- **WHEN** the upstream yields chat chunks
- **THEN** those chunks are forwarded
- **AND** the shutdown error frame is not yielded
