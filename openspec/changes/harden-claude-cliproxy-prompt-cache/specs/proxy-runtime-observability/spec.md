# proxy-runtime-observability (delta)

## ADDED Requirements

### Requirement: Pinned Claude turns are counted by prompt-cache hit

The system MUST count `codex_lb_cliproxy_claude_sticky_cache_total{result}` for every successful Claude response served by the conversation's existing, non-fallback CLIProxyAPI pin with a prompt of at least 4,096 tokens. `result` is `hit` when any cached input is reported and `miss` otherwise. Newly selected or rebound credentials, fallback pins, shorter prompts and other model families MUST NOT be counted.

#### Scenario: A gateway rewrites the body

- **GIVEN** a Claude conversation pinned to one credential
- **AND** its turns report no cached input although each prompt exceeds 4,096 tokens
- **WHEN** those turns are logged
- **THEN** each is counted as a `miss`

#### Scenario: The first turn on a new pin is not counted

- **GIVEN** a Claude request that the router routes to a newly selected credential
- **WHEN** it reports no cached input
- **THEN** nothing is counted

### Requirement: Pinned Claude cache misses are logged

CLIProxyAPI MUST reach `api.anthropic.com` directly, with nothing rewriting the request body in between; a counted miss signals that it does not. A counted miss MUST log `cliproxy_claude_sticky_cache_miss` with the provider, auth index, model and input tokens. The log MUST appear at most once every ten minutes per credential and MUST name the direct-to-`api.anthropic.com` requirement.

#### Scenario: Repeated misses on one credential

- **GIVEN** three counted misses on one credential within ten minutes
- **WHEN** they are recorded
- **THEN** one `cliproxy_claude_sticky_cache_miss` warning is logged for that credential

### Requirement: A sustained pinned Claude cache-miss rate alerts

The Helm chart MUST provide a `CodexLBClaudeStickyCacheMiss` warning alert. It fires when more than half of at least 10 counted turns over 30 minutes are misses, sustained for 15 minutes. A conversation idle past the cache TTL misses once and MUST NOT by itself reach that rate.

#### Scenario: Most pinned turns miss

- **GIVEN** at least 10 counted turns in 30 minutes, more than half of them misses, for 15 minutes
- **WHEN** Prometheus evaluates the rule
- **THEN** `CodexLBClaudeStickyCacheMiss` fires with severity `warning`
