# Fix Cursor Summarize Composer Routing

## Why

Cursor's `/summarize` command calls `POST /backend-api/codex/memories/trace_summarize`.
That endpoint currently uses the generic Codex control proxy and forwards the
request body as raw bytes. Unlike the Composer `/responses/compact` flow, this
path does not normalize Cursor GPT-5 model aliases, does not apply API-key model
or reasoning enforcement to the payload, and does not validate the effective
model before forwarding upstream.

As a result, `/summarize` can send a Cursor UI/session model label such as a
GPT-5 fast/reasoning alias directly to the ChatGPT control endpoint, while
mid-stream Composer compaction continues to work because it already runs through
the Responses policy pipeline.

## What Changes

- Normalize JSON payloads for `POST /backend-api/codex/memories/trace_summarize`
  before forwarding them to the Codex control upstream.
- Apply the same model alias, API-key enforced model, enforced reasoning effort,
  unsupported reasoning-effort, service-tier, and model-access policy used by
  Composer/Responses requests, while preserving trace-summarize-specific fields.
- Keep unrelated Codex control endpoints as raw pass-through routes.
- Add integration coverage proving summarize payloads are rewritten and invalid
  summarize payloads fail before upstream dispatch.

## Impact

- Affected spec: `responses-api-compat`.
- Affected code: `app/modules/proxy/api.py`,
  `tests/integration/test_proxy_api_extended.py`.
- No database or dashboard changes.
