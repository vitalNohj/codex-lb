## ADDED Requirements

### Requirement: Claude sidecar cooldown failures are labeled as cooldown in request logs

When a Claude sidecar request fails because CLIProxyAPI reports `auth_unavailable` or `no auth available`, the persisted request log MUST store `error_code` `claude_sidecar_cooldown` and an `error_message` that states cooldown and includes the request model. The client-facing error envelope MUST keep the original sidecar message. The original sidecar message MUST be retained on `failure_detail`.

#### Scenario: Non-stream Claude sidecar cooldown is logged as cooldown

- **GIVEN** CLIProxyAPI returns HTTP 503 with message `auth_unavailable: no auth available (providers=claude, model=claude-opus-5)`
- **WHEN** the proxy handles a non-streaming Claude sidecar `/v1/chat/completions` request
- **THEN** the request log stores `error_code = claude_sidecar_cooldown`
- **AND** the request log `error_message` states cooldown and includes the request model
- **AND** `failure_detail` retains the original `auth_unavailable` message
- **AND** the client response body still contains `auth_unavailable` or `no auth available`

#### Scenario: Stream Claude sidecar cooldown is logged as cooldown

- **GIVEN** CLIProxyAPI fails a streaming Claude sidecar chat completion with `no auth available`
- **WHEN** the proxy emits the terminal SSE error event
- **THEN** the request log stores `error_code = claude_sidecar_cooldown`
- **AND** the request log `error_message` states cooldown and includes the request model
- **AND** the SSE error envelope still contains `auth_unavailable` or `no auth available`

#### Scenario: Other Claude sidecar errors keep their original log message

- **GIVEN** CLIProxyAPI returns a Claude sidecar error that is not `auth_unavailable` / `no auth available` (for example `upstream returned error event: Overloaded`)
- **WHEN** the proxy persists the request log
- **THEN** `error_code` remains `claude_sidecar_error`
- **AND** `error_message` remains the original sidecar message
