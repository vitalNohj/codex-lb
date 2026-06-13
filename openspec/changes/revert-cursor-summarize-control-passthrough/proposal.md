# Revert Cursor Summarize Control Pass-Through

## Why

`POST /backend-api/codex/memories/trace_summarize` is a Codex *control*
endpoint, not a Responses endpoint. Upstream (`Soju06/codex-lb`) forwards its
request body to the ChatGPT/Codex backend completely unchanged, because that
backend already understands the Cursor-supplied model labels and control
payload shape.

A local change (`fix-cursor-summarize-composer-routing`) added
`_trace_summarize_control_payload`, which rewrote the `model`, injected
API-key enforced `reasoning` and `service_tier`, and ran model-access
validation on this control payload. That broke Cursor `/summarize`: with an
OpenAI API key enabled and a GPT-5 family model (e.g. `gpt-5.5`), the proxy
mutated the control payload with fields Cursor never sent, and the upstream
control endpoint rejected it. With the API key disabled (e.g. Composer 2.5),
no policy ran, so `/summarize` kept working — confirming the policy injection
as the regression.

## What Changes

- Revert `POST /backend-api/codex/memories/trace_summarize` to a raw
  pass-through that forwards the original request body unchanged, matching
  upstream and every other Codex control endpoint.
- Remove the trace-summarize policy adapter
  (`_trace_summarize_control_payload`, `_TraceSummarizePolicyPayload`) and the
  `payload_override` plumbing on the control proxy that only existed for it.
- Do NOT apply Responses/compact model-alias normalization, API-key
  enforcement, reasoning-effort normalization, service-tier policy, or
  model-access validation to Codex control payloads.
- Keep the separate compact-response relaxation (accepting `{"output": [...]}`
  without an `object` discriminator) untouched; it is unrelated to this
  regression.
- Add a regression test proving a GPT-5 alias summarize body is forwarded
  byte-for-byte even when an API key enforces reasoning/service tier.

## Impact

- Affected spec: `responses-api-compat`.
- Affected code: `app/modules/proxy/api.py`,
  `tests/integration/test_proxy_api_extended.py`,
  `tests/unit/test_proxy_trace_summarize.py` (removed).
- No database or dashboard changes.
