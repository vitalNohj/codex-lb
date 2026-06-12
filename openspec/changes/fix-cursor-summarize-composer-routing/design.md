# Design

## Problem

`/backend-api/codex/memories/trace_summarize` is a Codex control endpoint, not a
full Responses endpoint. The current API handler forwards its raw JSON body via
`context.service.codex_control_request`. Composer compaction uses
`ResponsesCompactRequest` and therefore receives API-key enforcement and Cursor
model-alias normalization, but trace summarize bypasses that policy layer.

The two paths also have different wire contracts:

- `/responses/compact` sends `model`, `instructions`, and Responses `input`, and
  the official Codex client parses the response as an `output` array of
  replacement `ResponseItem` values.
- `/memories/trace_summarize` sends `model`, `traces`, and optional `reasoning`,
  and the official Codex client parses the response as an `output` array of
  memory summary objects.

codex-lb must not turn trace summarize into compact input, and it must not
require compact responses to carry an OpenAI-style `object` discriminator.

## Approach

Keep the upstream route and generic control service unchanged. Add a narrow API
edge normalization path for `memories/trace_summarize`:

- read the JSON body at the route handler,
- if the body cannot be parsed as a JSON object, or the object does not contain
  a non-empty string `model`, keep forwarding the original bytes unchanged,
- adapt only the policy-managed fields (`model`, `reasoning`, `service_tier`)
  into a small Pydantic model that is compatible with `apply_api_key_enforcement`,
- validate the effective model with `validate_model_access`,
- write the normalized policy fields back into the original JSON object,
- serialize the JSON back to bytes and forward through `_codex_control_proxy`.

This avoids converting trace summarize into `ResponsesCompactRequest`, because
Cursor's control payload includes fields such as `traces` rather than the
`instructions`/`input` contract required by `/responses/compact`.

For compact responses, keep the existing response pass-through model but relax
the discriminator requirement. A payload with an `output` array is the canonical
Codex compact response and should parse and round-trip unchanged. Existing
object-discriminated payloads remain accepted for compatibility with older tests
and mocked deployments.

## Test Strategy

- Extend the existing control-endpoint integration test to show non-summarize
  control payloads are still forwarded unchanged.
- Add an integration test for `memories/trace_summarize` with a Cursor GPT-5
  alias and an API key enforcing reasoning/service tier.
- Add an integration test proving a summarize payload without `model` remains
  raw pass-through, preserving Cursor control-endpoint compatibility.
- Add unit and integration tests proving output-only compact responses parse and
  round-trip through the raw upstream HTTP path.
