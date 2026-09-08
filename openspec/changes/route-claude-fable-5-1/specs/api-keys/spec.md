## ADDED Requirements

### Requirement: GPT-6 Astra usage cost pricing matches the current published rates

When computing API-key usage, request-log, reservation, or aggregate cost for `gpt-6-astra`, the system MUST use these USD-per-1M-token rates for input, cached input, and output:

| Model | Standard | Fast/priority | Flex | Standard long context |
| --- | --- | --- | --- | --- |
| `gpt-6-astra` | `10 / 1 / 50` | `20 / 2 / 100` | `5 / 0.50 / 25` | `20 / 2 / 75` |

The existing `priority` and `fast` service-tier aliases MUST use the Fast/priority rates. Standard long-context rates MUST apply only when input tokens exceed 272,000. Flex long-context pricing MUST continue to use the existing Flex short-context rates and multipliers. Suffixed aliases such as `gpt-6-astra-2026-09-03` and the discoverable alias `codex/gpt-6-astra` MUST resolve to the canonical `gpt-6-astra` price entry.

#### Scenario: Astra standard usage uses the current rate

- **WHEN** a standard-tier `gpt-6-astra` request has 200,000 input tokens, 100,000 cached input tokens, and 1,000,000 output tokens
- **THEN** the token cost is `$51.10`

#### Scenario: Astra Fast and Flex usage use their tier rates

- **WHEN** a `gpt-6-astra` request has 200,000 input tokens, 100,000 cached input tokens, and 1,000,000 output tokens
- **AND** the request uses `priority` or `fast`
- **THEN** the token cost is `$102.20`
- **WHEN** the same usage uses `flex`
- **THEN** the token cost is `$25.55`

#### Scenario: Astra standard long-context usage uses the current long-context rate

- **WHEN** a standard-tier `gpt-6-astra` request has 300,000 input tokens, 50,000 cached input tokens, and 100,000 output tokens
- **THEN** the token cost is `$12.60`

### Requirement: Claude Fable 5.1 pricing is distinct from Fable 5

The native price table MUST recognize Anthropic Claude Fable 5.1, including sidecar-prefixed and dotted ids such as `cc/claude-fable-5-1` and `cc/claude-fable-5.1`. Its cache-read rate MUST remain distinct from Fable 5's. External integration request-log costs remain governed by `external-model-pricing`: catalog prices and authoritative billed amounts MUST NOT be replaced with these native rates.

#### Scenario: Canonical Fable 5.1 model resolves pricing

- **WHEN** native cost accounting resolves model `claude-fable-5-1` with token usage
- **THEN** it uses the preserved Fable 5.1 native rates ($10 input / $0.25 cache-hit / $50 output per 1M tokens)

#### Scenario: Sidecar-prefixed Fable 5.1 does not use Fable 5 cache-hit pricing

- **WHEN** native price lookup receives model `cc/claude-fable-5-1`
- **THEN** it resolves the distinct Fable 5.1 native price entry
- **AND** the resolved canonical model is `claude-fable-5-1`

