## ADDED Requirements

### Requirement: OrcaRouter chat completions retry one provider failure
OrcaRouter `POST /v1/chat/completions` dispatch MUST send the same payload once more when the first attempt fails with HTTP status 500 or higher and no response byte has been sent to the client. HTTP 524, 502, 503, and 504 MUST be retried. Transport failures reported as HTTP 503 MUST be retried. The client MUST receive the second attempt's result. A second provider failure MUST be returned once. HTTP 4xx MUST NOT be retried. A stream that has already yielded a chunk MUST NOT be retried. The request log MUST contain one row for the final outcome.

#### Scenario: Gateway timeout is retried and the second attempt succeeds

- **GIVEN** OrcaRouter is enabled and owns the requested model
- **WHEN** the first non-streaming attempt returns HTTP 524
- **AND** the second attempt returns a chat completion
- **THEN** the client receives HTTP 200 with that completion
- **AND** OrcaRouter was called twice
- **AND** the request log has one success row

#### Scenario: Repeated provider failure is returned once

- **GIVEN** OrcaRouter is enabled and owns the requested model
- **WHEN** both attempts return HTTP 524
- **THEN** the client receives the provider error
- **AND** OrcaRouter was called twice
- **AND** the request log has one error row

#### Scenario: Client errors are not retried

- **GIVEN** OrcaRouter is enabled and owns the requested model
- **WHEN** the first attempt returns HTTP 400
- **THEN** the client receives that error
- **AND** OrcaRouter was called once

#### Scenario: Streaming provider failure is retried before any chunk

- **GIVEN** OrcaRouter is enabled and owns the requested model
- **WHEN** a streaming attempt fails with HTTP 502 before any chunk
- **AND** the next attempt streams a completion
- **THEN** the client receives that completion stream
- **AND** the client does not receive an error event from the failed attempt

#### Scenario: A started stream is not retried

- **GIVEN** OrcaRouter is enabled and owns the requested model
- **WHEN** a streaming attempt yields a chunk and then fails
- **THEN** OrcaRouter is not called again
- **AND** the client receives an error event after the chunk already sent
