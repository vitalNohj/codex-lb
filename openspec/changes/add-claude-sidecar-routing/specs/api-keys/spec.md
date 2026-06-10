## MODIFIED Requirements

### Requirement: Model restriction enforcement

The system SHALL enforce per-key model restrictions in the proxy service layer (not middleware). When `allowed_models` is set (non-null, non-empty) and the requested model is not in the list, the system MUST reject the request. The `/v1/models` endpoint MUST filter the model list based on the authenticated key's `allowed_models`.

For fixed-model endpoints such as `/v1/audio/transcriptions` and `/backend-api/transcribe`, the service MUST evaluate restrictions against fixed effective model `gpt-4o-transcribe`.

`/backend-api/codex/models` SHALL keep the existing allowlist filtering behavior by default. When an authenticated API key has `apply_to_codex_model = true` and `allowed_models` is non-empty, `/backend-api/codex/models` SHALL return the full catalog and rewrite each model entry visibility so allowlisted models use `visibility: "list"` and every other model uses `visibility: "hide"`. When `apply_to_codex_model = true` but `allowed_models` is null or empty, `/backend-api/codex/models` SHALL preserve the original behavior because there is no allowlist to apply.

When Claude sidecar routing is enabled, the same model restriction enforcement MUST apply before a sidecar request is forwarded. An API key whose `allowed_models` excludes the effective Claude sidecar model MUST receive the existing model-not-allowed error and the sidecar MUST NOT receive the request.

#### Scenario: Sidecar model not allowed

- **GIVEN** `claude_sidecar_enabled=true`
- **AND** a key has `allowed_models: ["gpt-5.4"]`
- **WHEN** the key sends `POST /v1/chat/completions` with `model: "claude-sonnet-4-5-20250929"`
- **THEN** the proxy returns 403 with OpenAI-format error code `model_not_allowed`
- **AND** the sidecar receives no request

#### Scenario: Sidecar model allowed

- **GIVEN** `claude_sidecar_enabled=true`
- **AND** a key has `allowed_models: ["claude-sonnet-4-5-20250929"]`
- **WHEN** the key sends `POST /v1/chat/completions` with `model: "claude-sonnet-4-5-20250929"`
- **THEN** the proxy forwards the request to the sidecar

### Requirement: API-key usage reservations cover Claude sidecar requests

When an authenticated API key sends a Claude sidecar chat-completions request, the service MUST create an API-key usage reservation before forwarding the request to the sidecar. The reservation MUST be finalized exactly once with token counts from the sidecar response usage object when usage is available. If usage is missing, the sidecar request fails before usable response usage is available, or the downstream client disconnects before streaming completes, the reservation MUST be released exactly once.

#### Scenario: Non-streaming sidecar usage finalizes reservation

- **GIVEN** an authenticated API key with request limits
- **AND** the sidecar returns a non-streaming chat-completions response with `usage.prompt_tokens=10` and `usage.completion_tokens=5`
- **WHEN** the request completes successfully
- **THEN** the API-key reservation is finalized once for the effective Claude model with 10 input tokens and 5 output tokens

#### Scenario: Streaming sidecar usage finalizes reservation

- **GIVEN** an authenticated API key with request limits
- **AND** the sidecar emits a final streaming usage chunk with `prompt_tokens=10` and `completion_tokens=5`
- **WHEN** the stream reaches `data: [DONE]`
- **THEN** the API-key reservation is finalized once for the effective Claude model with 10 input tokens and 5 output tokens

#### Scenario: Sidecar failure releases reservation

- **GIVEN** an authenticated API key with request limits
- **AND** the sidecar is unreachable
- **WHEN** the key sends a Claude sidecar chat-completions request
- **THEN** the API-key reservation is released once

#### Scenario: Missing usage releases reservation

- **GIVEN** an authenticated API key with request limits
- **AND** the sidecar returns a successful response without a `usage` object
- **WHEN** the request completes
- **THEN** the API-key reservation is released once
