## Why

OrcaRouter chat requests fail closed on the first upstream provider error. HTTP 524 and 502 from `z-ai/glm-*` are the provider behind OrcaRouter staying silent or dying at its gateway. codex-lb returns that status to the client immediately, so OrcaRouter never gets a second request on which it can choose a different provider.

## What Changes

- Retry an OrcaRouter, OpenRouter, NVIDIA, OpenCode Go, or plus-button OpenAI-compatible chat completion once when the failure is a provider/transport error (HTTP status >= 500, including 502, 503, 504, and 524) and no response byte has been sent to the client. OpenCode Go's Responses adapter uses the same retry.
- Return the second attempt's result. If that attempt also fails, surface that failure once.
- Do not retry HTTP 4xx. Do not retry a stream after any chunk has already been sent. Do not retry an OpenCode Go body that exceeds the size limit.
- Keep a single request-log row for the final outcome.

## Capabilities

### New Capabilities

### Modified Capabilities

- `chat-completions-compat`: OrcaRouter chat completions retry one provider failure before returning it to the client.

## Impact

- `app/modules/proxy/sidecar_upstream_errors.py` holds the shared retry rule.
- Dispatch for OrcaRouter, OpenRouter, NVIDIA, OpenCode Go, and plus-button OpenAI-compatible endpoints. No settings, schema, or client-contract change.
- A failed attempt that hangs until OrcaRouter's edge timeout (~300s) makes the client wait through that attempt plus the retry. The configured OrcaRouter request timeout stays 600s per attempt.
