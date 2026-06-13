## ADDED Requirements

### Requirement: Codex control endpoints forward request bodies unchanged

The proxy MUST forward Codex control endpoint request bodies to the upstream
Codex control path unchanged, including
`POST /backend-api/codex/memories/trace_summarize`. The proxy MUST NOT
apply Responses or compact request policy to control payloads: it MUST NOT
normalize Cursor GPT-5 model aliases, MUST NOT rewrite the `model`, MUST NOT
inject or enforce `reasoning` effort or `service_tier`, and MUST NOT run
API-key model-access validation against control payloads.

This requirement applies regardless of whether API-key authentication is
enabled or whether the authenticated key declares an enforced model, enforced
reasoning effort, enforced service tier, or an allowed-model list. Control
endpoints remain raw pass-through routes.

#### Scenario: Cursor summarize body is forwarded unchanged

- **GIVEN** a client sends `POST /backend-api/codex/memories/trace_summarize`
  with `model = "gpt-5.5-low-fast"`, `traces`, and `metadata`
- **WHEN** the proxy forwards the request upstream
- **THEN** the forwarded body equals the original body byte-for-byte
- **AND** the forwarded `model` is still `"gpt-5.5-low-fast"`
- **AND** no `reasoning` or `service_tier` field is added

#### Scenario: Cursor summarize body is unchanged under an enforcing API key

- **GIVEN** API-key auth is enabled and the key enforces reasoning effort and
  service tier and lists allowed models
- **WHEN** a client sends `POST /backend-api/codex/memories/trace_summarize`
  with that key and a GPT-5 family model label
- **THEN** the proxy forwards the original control body unchanged
- **AND** the proxy does not reject the request via model-access validation

#### Scenario: Summarize without a model is forwarded unchanged

- **WHEN** a client sends `POST /backend-api/codex/memories/trace_summarize`
  with a JSON object that has no string `model` field
- **THEN** the proxy forwards the payload unchanged to the upstream control path
