# responses-api-compat (delta)

## ADDED Requirements

### Requirement: xAI Responses requests take CLIProxyAPI's native Responses route

When `CODEX_LB_CLIPROXY_XAI_NATIVE_RESPONSES_ENABLED` is on, a `/v1/responses` request served by CLIProxyAPI for a plain xAI wire model MUST go to CLIProxyAPI's `/v1/responses` and MUST NOT go through the Responses-to-chat bridge. A plain xAI wire model has no `/` and starts with `grok`. Every other CLIProxyAPI model and every other provider MUST keep the bridge. When the setting is off, xAI MUST take the bridge.

The forwarded body MUST equal the client's request except for three changes: `model` is set to the routed wire model, `prompt_cache_key` is set, and an operator default reasoning effort is set only when the client sent none. Reasoning items MUST keep their `encrypted_content` byte-for-byte. The upstream response, streamed or not, MUST reach the client unchanged.

#### Scenario: Encrypted reasoning survives later turns

- **GIVEN** an xAI conversation whose earlier turns returned reasoning items with `encrypted_content`
- **WHEN** the client replays those items on the next `/v1/responses` turn
- **THEN** CLIProxyAPI receives each item's `encrypted_content` byte-for-byte, in order

#### Scenario: Responses-only fields are kept

- **GIVEN** an xAI request with `instructions`, `reasoning.summary` and a client `reasoning.effort`
- **WHEN** it is forwarded
- **THEN** each field reaches CLIProxyAPI as the client sent it, even when an operator default effort is configured

#### Scenario: Other models keep the bridge

- **GIVEN** a CLIProxyAPI request for a Claude model or a prefixed id such as `devin/grok-4-6`
- **WHEN** it is dispatched
- **THEN** it is translated to chat completions as before

#### Scenario: The switch restores the bridge

- **GIVEN** `CODEX_LB_CLIPROXY_XAI_NATIVE_RESPONSES_ENABLED=false`
- **WHEN** an xAI `/v1/responses` request is dispatched
- **THEN** it goes through the chat bridge

### Requirement: The native xAI route keeps the chat route's guards

The native xAI route MUST reject `previous_response_id`, `conversation` and `store: true` with a 400 before reserving quota, because CLIProxyAPI does not store responses. It MUST enforce the API key's service tier and take the same usage reservation as the chat route. It MUST use the chat route's account selection, sticky pins, cooldown waits and 401/403/429 rebind.

#### Scenario: previous_response_id is refused before reservation

- **GIVEN** an xAI request with `previous_response_id`
- **WHEN** it reaches the native route
- **THEN** codex-lb answers 400, reserves no quota and sends nothing to CLIProxyAPI

### Requirement: The native xAI route always sends the conversation's cache key

Every native xAI request MUST carry a non-empty `prompt_cache_key`. That key MUST be the identity the conversation's CLIProxyAPI sticky pin is keyed on: the client's `prompt_cache_key`, a session header, or the derived key. When the request has no identity, codex-lb MUST send a fresh random key and MUST NOT pin it, so CLIProxyAPI never falls back to its message-derived key.

#### Scenario: Cache key equals the pin identity

- **GIVEN** a multi-turn xAI conversation through the native route
- **WHEN** each turn reaches xAI
- **THEN** every turn carries the same `prompt_cache_key` and `x-grok-conv-id`
- **AND** the CLIProxyAPI sticky pin is keyed on that value

### Requirement: The native xAI route records Responses usage and xAI's billed cost

The native xAI route MUST read cached input tokens and reasoning tokens from the Responses `usage` object. When `usage.cost_in_usd_ticks` is a positive integer, it MUST record `cost_in_usd_ticks / 10^10` USD as the upstream-billed request cost, for streaming and non-streaming requests, and settle the reservation on it. A turn that fails after reporting usage MUST still be charged. A turn without usage MUST release the reservation. A stream that ends without a terminal event MUST end with a `response.failed` frame and be logged as an error.

#### Scenario: xAI ticks become the billed cost

- **GIVEN** an xAI response whose usage reports `cost_in_usd_ticks: 123456789`, 1024 cached tokens and 48 reasoning tokens
- **WHEN** the request log is written
- **THEN** the cost is 0.0123456789 USD with upstream-billed provenance
- **AND** the cached and reasoning token counts are 1024 and 48
