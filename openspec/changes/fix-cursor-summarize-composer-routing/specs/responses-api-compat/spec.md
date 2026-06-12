## MODIFIED Requirements

### Requirement: Codex compaction requests use Responses policy normalization

Composer compaction requests and Cursor summarize control requests MUST apply the
Responses request policy before reaching the upstream ChatGPT backend. For
`POST /backend-api/codex/responses/compact`, `POST /v1/responses/compact`, and
`POST /backend-api/codex/memories/trace_summarize`, the proxy MUST normalize
supported Cursor GPT-5 model aliases to canonical upstream model slugs, apply
API-key enforced model, reasoning-effort, and service-tier policy, normalize
unsupported upstream reasoning efforts, and validate the effective model against
API-key model access.

For `POST /backend-api/codex/memories/trace_summarize`, the proxy MUST preserve
trace-summarize-specific JSON fields such as `raw_memories` and MUST forward the
request to the same upstream control path after rewriting only the policy-managed
fields. Other Codex control endpoints MUST remain raw pass-through endpoints
unless a separate compatibility rule says otherwise.

#### Scenario: Cursor summarize model alias is rewritten before upstream control dispatch

- **GIVEN** a client sends `POST /backend-api/codex/memories/trace_summarize`
  with `model = "gpt-5.5-high-fast"`
- **WHEN** the proxy forwards the request upstream
- **THEN** the forwarded payload has `model = "gpt-5.5"`
- **AND** the forwarded payload has `reasoning.effort = "high"`
- **AND** the forwarded payload has `service_tier = "priority"`
- **AND** trace-summarize fields such as `raw_memories` are preserved

#### Scenario: Cursor summarize honors API-key enforced policy

- **GIVEN** API-key auth is enabled and the key enforces model, reasoning
  effort, or service tier
- **WHEN** a client sends `POST /backend-api/codex/memories/trace_summarize`
  with that key
- **THEN** the forwarded control payload uses the enforced model and policy
  fields
- **AND** model-access validation runs against the effective model before
  upstream dispatch

#### Scenario: Other Codex control endpoints stay raw

- **WHEN** a client sends JSON to a Codex control endpoint other than
  `memories/trace_summarize`
- **THEN** the proxy forwards that payload without applying summarize policy
  rewrites
