## ADDED Requirements

### Requirement: Soft sticky mappings must rebind after pre-visible usage exhaustion

When a prompt-cache or other explicitly soft sticky mapping selected an account that then fails before downstream-visible output with `usage_limit_reached`, `insufficient_quota`, `quota_exceeded`, or `usage_not_included`, and failover selects a replacement, the service MUST persist the mapping onto that replacement so later requests with the same sticky key do not return to the exhausted account. The service MUST NOT introduce a separate dead-endpoint cooldown denylist for this path. Hard Codex-session, previous-response, turn-state, and file pins MUST remain owner-bound.

#### Scenario: Resume after usage-limit failover uses the replacement account

- **GIVEN** a prompt-cache mapping points at account A
- **AND** a request on that mapping fails pre-visible with `usage_limit_reached`
- **AND** the same request completes on account B
- **WHEN** a later request arrives with the same prompt-cache key
- **THEN** selection prefers account B rather than retrying account A solely because it was the previous pin

#### Scenario: Short rate-limit blips keep the original prompt-cache pin

- **GIVEN** a prompt-cache mapping points at account A
- **AND** account A is only briefly `rate_limit_exceeded`
- **WHEN** selection falls back to account B for the current request
- **THEN** the stored mapping remains account A so a later request can return to the warm cache
