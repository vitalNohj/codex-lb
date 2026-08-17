## ADDED Requirements

### Requirement: Claude sidecar cooldown failures are labeled as cooldown in request logs

When a Claude sidecar request fails because CLIProxyAPI reports `auth_unavailable` or `no auth available` and the proxy wait budget is exhausted, the persisted request log MUST store `error_code` `claude_sidecar_cooldown` and an `error_message` that states cooldown and includes the request model. The client-facing error envelope MUST keep the original sidecar message. The original sidecar message MUST be retained on `failure_detail`.

#### Scenario: Non-stream Claude sidecar cooldown is logged as cooldown

- **GIVEN** CLIProxyAPI returns HTTP 503 with message `auth_unavailable: no auth available (providers=claude, model=claude-opus-5)` for the whole wait budget
- **WHEN** the proxy handles a non-streaming Claude sidecar `/v1/chat/completions` request
- **THEN** the request log stores `error_code = claude_sidecar_cooldown`
- **AND** the request log `error_message` states cooldown and includes the request model
- **AND** `failure_detail` retains the original `auth_unavailable` message
- **AND** the client response body still contains `auth_unavailable` or `no auth available`

#### Scenario: Stream Claude sidecar cooldown is logged as cooldown

- **GIVEN** CLIProxyAPI fails a streaming Claude sidecar chat completion with `no auth available` for the whole wait budget
- **WHEN** the proxy emits the terminal SSE error event
- **THEN** the request log stores `error_code = claude_sidecar_cooldown`
- **AND** the request log `error_message` states cooldown and includes the request model
- **AND** the SSE error envelope still contains `auth_unavailable` or `no auth available`

#### Scenario: Other Claude sidecar errors keep their original log message

- **GIVEN** CLIProxyAPI returns a Claude sidecar error that is not `auth_unavailable` / `no auth available` (for example `upstream returned error event: Overloaded`)
- **WHEN** the proxy persists the request log
- **THEN** `error_code` remains `claude_sidecar_error`
- **AND** `error_message` remains the original sidecar message

### Requirement: Claude sidecar cooldown 503s are waited out before the client sees an error

The proxy MUST retry a Claude sidecar `auth_unavailable` / `no auth available` failure for a bounded wait instead of immediately returning that error to the client. Anthropic `Overloaded` and other non-cooldown sidecar errors MUST NOT be retried. If a retry succeeds, the client MUST receive the successful response and the request log MUST be `success`. If the wait budget expires, the client MUST receive exactly one error with the original sidecar message.

#### Scenario: Non-stream cooldown clears before the wait budget expires

- **GIVEN** CLIProxyAPI returns HTTP 503 `auth_unavailable` on the first attempt and a successful chat completion on the next attempt within the wait budget
- **WHEN** the proxy handles a non-streaming Claude sidecar `/v1/chat/completions` request
- **THEN** the client receives HTTP 200
- **AND** the client body does not contain `auth_unavailable`
- **AND** the request log status is `success`

#### Scenario: Stream cooldown clears before the wait budget expires

- **GIVEN** CLIProxyAPI fails stream open with `no auth available` once, then streams successfully within the wait budget
- **WHEN** the proxy handles a streaming Claude sidecar `/v1/chat/completions` request
- **THEN** the SSE body contains no error event
- **AND** the request log status is `success`

#### Scenario: Overloaded is not retried as cooldown

- **GIVEN** CLIProxyAPI returns `upstream returned error event: Overloaded`
- **WHEN** the proxy handles the Claude sidecar request
- **THEN** the error is returned without cooldown retries
- **AND** `error_code` remains `claude_sidecar_error`

### Requirement: Concurrent Claude sidecar cooldown waiters park on a shared wait

The proxy MUST share one Claude sidecar cooldown wait across concurrent in-flight requests. Extra waiters MUST park until the shared cooldown elapses or a probe succeeds; they MUST NOT fail-fast with a cooldown 503 while the wait budget remains. While cooling, sidecar probes MUST be single-flight.

#### Scenario: Concurrent cooldown waiters park instead of fail-fast

- **GIVEN** CLIProxyAPI is cooling Claude auths and returns `auth_unavailable` to a probe
- **WHEN** several Claude sidecar `/v1/chat/completions` requests are already in flight
- **THEN** extra waiters park on the shared cooldown
- **AND** they do not each receive a fail-fast cooldown 503
- **AND** only one probe runs at a time until cooling clears
