## MODIFIED Requirements

### Requirement: Codex compaction requests use Responses policy normalization

Composer compaction requests MUST apply the Responses request policy before
reaching the upstream ChatGPT backend. For
`POST /backend-api/codex/responses/compact` and `POST /v1/responses/compact`,
the proxy MUST normalize supported Cursor GPT-5 model aliases to canonical
upstream model slugs, apply API-key enforced model, reasoning-effort, and
service-tier policy, normalize unsupported upstream reasoning efforts, and
validate the effective model against API-key model access.

Compact responses MUST preserve the official Codex compact response contract.
When upstream returns a JSON object containing an `output` array and no `object`
discriminator, the proxy MUST treat it as a successful compact response and
return that payload unchanged to the client. The proxy MAY continue accepting
object-discriminated compact response payloads for compatibility, but it MUST
NOT require that discriminator for successful compaction.

For `POST /backend-api/codex/memories/trace_summarize`, the proxy MUST preserve
trace-summarize-specific JSON fields such as `traces` and MUST forward the
request to the same upstream control path without converting it into
`instructions`/`input` compact input. When the summarize payload is a JSON
object with a non-empty string `model`, the proxy MUST apply the same supported
Cursor GPT-5 model alias normalization, API-key enforced model,
reasoning-effort, service-tier policy, unsupported-reasoning normalization, and
model-access validation to the policy-managed fields before forwarding. When
the summarize payload does not include a usable `model` field, the proxy MUST
forward the payload unchanged rather than rejecting the control request. Other
Codex control endpoints MUST remain raw pass-through endpoints unless a separate
compatibility rule says otherwise.

#### Scenario: Output-only compact response round trips

- **GIVEN** upstream accepts `POST /backend-api/codex/responses/compact`
- **AND** upstream returns `{"output": [...]}` without an `object` field
- **WHEN** the proxy parses the upstream compact response
- **THEN** the proxy returns HTTP 200 to the client
- **AND** the downstream response body preserves the same `output` array

#### Scenario: Cursor summarize model alias is rewritten before upstream control dispatch

- **GIVEN** a client sends `POST /backend-api/codex/memories/trace_summarize`
  with `model = "gpt-5.5-high-fast"`
- **WHEN** the proxy forwards the request upstream
- **THEN** the forwarded payload has `model = "gpt-5.5"`
- **AND** the forwarded payload has `reasoning.effort = "high"`
- **AND** the forwarded payload has `service_tier = "priority"`
- **AND** trace-summarize fields such as `traces` are preserved

#### Scenario: Cursor summarize honors API-key enforced policy

- **GIVEN** API-key auth is enabled and the key enforces model, reasoning
  effort, or service tier
- **WHEN** a client sends `POST /backend-api/codex/memories/trace_summarize`
  with that key
- **THEN** the forwarded control payload uses the enforced model and policy
  fields
- **AND** model-access validation runs against the effective model before
  upstream dispatch

#### Scenario: Cursor summarize without a model stays raw

- **WHEN** a client sends `POST /backend-api/codex/memories/trace_summarize`
  with a JSON object that has no string `model` field
- **THEN** the proxy forwards the payload unchanged to the upstream control path
- **AND** the proxy does not reject the request for failing a Responses or
  compact-request schema

#### Scenario: Other Codex control endpoints stay raw

- **WHEN** a client sends JSON to a Codex control endpoint other than
  `memories/trace_summarize`
- **THEN** the proxy forwards that payload without applying summarize policy
  rewrites
