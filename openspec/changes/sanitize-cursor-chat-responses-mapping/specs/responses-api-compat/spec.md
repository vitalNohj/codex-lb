## ADDED Requirements

### Requirement: Strip chat-only extras from forwarded Responses payloads

Before classifying or forwarding a Responses payload, the service MUST strip chat-only extras that are not Responses parameters so they cannot fail account-neutral replay or trigger upstream `unknown_parameter`. At minimum the service MUST strip `frequency_penalty`, `presence_penalty`, `seed`, `logprobs`, `top_logprobs`, `logit_bias`, and `stop` in addition to the existing unsupported advisory set (`temperature`, `top_p`, `user`, `metadata`, `prompt_cache_retention`, `safety_identifier`, `max_output_tokens`, `truncation`).

#### Scenario: Chat penalty extras are stripped

- **WHEN** a chat-mapped or extra-allow Responses request includes `frequency_penalty`, `presence_penalty`, `seed`, `logit_bias`, `logprobs`, or `stop`
- **THEN** those fields are absent from the forwarded payload and from the account-neutral replay projection
