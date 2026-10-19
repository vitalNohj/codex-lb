# sticky-session-operations (delta)

## ADDED Requirements

### Requirement: codex-lb reports CLIProxyAPI session affinity

Each CLIProxyAPI quota poll MUST read `routing.session-affinity`, publish the result as `codex_lb_cliproxy_session_affinity_enabled`, and log a warning when affinity is off. The warning MUST repeat at most hourly while affinity stays off. A failed read MUST NOT fail the poll. codex-lb MUST NOT change the setting itself. The dashboard session-affinity toggle MUST show a warning when the setting reads off.

#### Scenario: Affinity off is warned about

- **GIVEN** CLIProxyAPI with `routing.session-affinity: false`
- **WHEN** the quota poller runs
- **THEN** the gauge reads 0 and a warning naming session affinity is logged
- **AND** the poll still records the credentials' quota

#### Scenario: An unreadable setting does not break the poll

- **GIVEN** the management API fails when the affinity setting is read
- **WHEN** the quota poller runs
- **THEN** the poll completes normally
