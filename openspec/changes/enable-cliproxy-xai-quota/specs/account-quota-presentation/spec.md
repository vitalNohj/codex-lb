# account-quota-presentation (delta)

## ADDED Requirements

### Requirement: Polled xAI CLIProxyAPI logins appear on their own provider card

Each CLIProxyAPI quota poll MUST store the xAI logins it lists, with their Grok credit windows and prepaid credits.
The dashboard overview and the accounts list MUST show them on one read-only `cliproxy-xai` card under the CLIProxy account-type filter.

#### Scenario: A mixed listing shows an xAI card beside the Claude card

- **GIVEN** CLIProxyAPI lists two Claude logins and one xAI login
- **WHEN** the quota poller runs
- **THEN** the overview and the accounts list include a `cliproxy-xai` card with the xAI login, its Grok windows, and its prepaid credits
- **AND** the Claude sidecar card still lists exactly the two Claude logins

### Requirement: xAI quota never changes a Claude login

An xAI rate-limit hold MUST NOT disable or enable a Claude login.
Claude quota, estimates, and the Claude card MUST keep reading only Claude rows.
A stalled Grok credits fetch MUST give up after its own short timeout, and the poll MUST run those fetches concurrently, so a stalled xAI login does not hold back saving Claude quota and hold releases for the general sidecar request timeout.

#### Scenario: Stalled Grok fetches do not hold back the Claude quota

- **GIVEN** a Claude login and three xAI logins whose Grok credits fetch never answers
- **WHEN** the quota poller runs
- **THEN** the poll finishes after about one Grok fetch timeout, not one per xAI login
- **AND** it saves the Claude quota and keeps each xAI login's stored Grok windows

#### Scenario: An xAI hold leaves a Claude pause alone

- **GIVEN** an operator-paused Claude login and an xAI login under an expired hold
- **WHEN** one poll releases the xAI hold and the next sees a free-usage 429 for it
- **THEN** only the xAI login is enabled and then disabled
- **AND** the Claude login stays paused with no PATCH sent for it
