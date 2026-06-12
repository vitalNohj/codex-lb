# Fix Cursor Summarize Composer Routing

## Why

Cursor/Codex uses two separate summary-like paths:

- conversation context compaction: `POST /backend-api/codex/responses/compact`,
  which sends fully resolved Responses history and expects an `output` array of
  replacement response items;
- memory trace summarization:
  `POST /backend-api/codex/memories/trace_summarize`, which sends memory
  `traces` and expects an `output` array of memory summaries.

The trace summarize endpoint currently uses the generic Codex control proxy and
forwards the request body as raw bytes. Unlike the Composer
`/responses/compact` flow, this path does not normalize Cursor GPT-5 model
aliases, does not apply API-key model or reasoning enforcement to the payload,
and does not validate the effective model before forwarding upstream.

Separately, codex-lb's compact response model currently requires an
object discriminator such as `response.compaction`, but the open-source Codex
compact client parses the upstream response as `{"output": [...]}`. When the
real upstream returns the official output-only shape, codex-lb rejects the
successful compaction as an unexpected payload, so Cursor never receives the
compacted history replacement and can continue until context length is exceeded.

As a result, `/summarize` can send a Cursor UI/session model label such as a
GPT-5 fast/reasoning alias directly to the ChatGPT control endpoint, while
mid-stream Composer compaction continues to work because it already runs through
the Responses policy pipeline.

## What Changes

- Normalize JSON payloads for `POST /backend-api/codex/memories/trace_summarize`
  before forwarding them to the Codex control upstream when the payload includes
  a usable `model` field.
- Apply the same model alias, API-key enforced model, enforced reasoning effort,
  unsupported reasoning-effort, service-tier, and model-access policy used by
  Composer/Responses requests, while preserving trace-summarize-specific fields.
- Keep unrelated Codex control endpoints as raw pass-through routes.
- Accept and pass through the official Codex compact response shape
  `{"output": [...]}` while preserving compatibility with older
  object-discriminated compact responses.
- Keep trace summarize payloads on their official wire shape, preserving
  `traces` fields rather than converting them to Responses compact input.
- Add coverage proving summarize payloads with a model are rewritten and
  summarize payloads without a model remain raw pass-through.

## Impact

- Affected spec: `responses-api-compat`.
- Affected code: `app/modules/proxy/api.py`,
  `tests/integration/test_proxy_api_extended.py`.
- No database or dashboard changes.
