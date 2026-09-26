## ADDED Requirements

### Requirement: Disable an exhausted CLIProxyAPI auth until its reset
A Claude sidecar quota poll MUST disable a CLIProxyAPI Claude auth when one or more of its 5h or weekly usage windows has remaining percent at or below 0 and a reset time strictly after the poll time, and it MUST keep that auth disabled until the latest such reset time.

#### Scenario: Five-hour window is empty
- **GIVEN** a Claude auth is enabled
- **AND** its 5h window has remaining percent 0 with a reset time in the future
- **AND** its weekly window has remaining percent above 0
- **WHEN** the Claude sidecar quota poll runs
- **THEN** codex-lb sets that auth file's `disabled` field to true
- **AND** the stored hold lasts until the 5h reset time

#### Scenario: Both windows are empty
- **GIVEN** a Claude auth is enabled
- **AND** its 5h window and its weekly window each have remaining percent 0 with reset times in the future
- **WHEN** the Claude sidecar quota poll runs
- **THEN** codex-lb sets that auth file's `disabled` field to true
- **AND** the stored hold lasts until the later of the two reset times

#### Scenario: Missing or past reset does not disable
- **GIVEN** a Claude auth is enabled
- **AND** a usage window has remaining percent 0
- **AND** that window's reset time is missing or not after the poll time
- **AND** no other window has remaining percent at or below 0 with a reset time after the poll time
- **WHEN** the Claude sidecar quota poll runs
- **THEN** codex-lb does not change that auth file's `disabled` field

#### Scenario: Remaining percent above zero does not disable
- **GIVEN** a Claude auth is enabled
- **AND** both usage windows have remaining percent above 0
- **AND** the auth status message describes a rate limit
- **WHEN** the Claude sidecar quota poll runs
- **THEN** codex-lb does not change that auth file's `disabled` field

### Requirement: Enable an auth when its owned hold expires
When a Claude sidecar quota poll no longer finds a future exhausted window for an auth that this poller disabled, codex-lb MUST set that auth file's `disabled` field to false and MUST drop the owned hold.

#### Scenario: Window has recovered
- **GIVEN** the quota snapshot records an unreleased hold for a Claude auth
- **AND** that auth file is disabled
- **AND** the latest usage no longer has a window at or below 0 percent remaining with a reset time after the poll time
- **WHEN** the Claude sidecar quota poll runs
- **THEN** codex-lb sets that auth file's `disabled` field to false
- **AND** the snapshot no longer records a hold for that auth

### Requirement: Leave an operator pause in place
codex-lb MUST NOT enable a Claude auth that is already disabled unless the quota snapshot records an unreleased hold owned by this poller for that auth.

#### Scenario: Operator pause is not adopted
- **GIVEN** a Claude auth file is already disabled
- **AND** the quota snapshot has no hold for that auth
- **AND** a usage window is exhausted with a reset time in the future
- **WHEN** the Claude sidecar quota poll runs
- **THEN** codex-lb does not change that auth file's `disabled` field
- **AND** the snapshot still has no hold for that auth

#### Scenario: Operator pause stays after the window clears
- **GIVEN** a Claude auth file is disabled
- **AND** the quota snapshot has no unreleased hold for that auth
- **AND** neither usage window is exhausted
- **WHEN** the Claude sidecar quota poll runs
- **THEN** codex-lb leaves that auth file disabled

### Requirement: Honor explicit resume for the same reset
A successful resume of a Claude auth MUST record a released hold for the exhausted-window reset time shown by the current quota snapshot, and later quota polls MUST NOT disable that auth again while the computed reset time stays the same.

#### Scenario: Resume during an exhausted window
- **GIVEN** a Claude auth is disabled
- **AND** its current usage has a future exhausted-window reset time
- **WHEN** an operator resumes that auth
- **THEN** codex-lb sets that auth file's `disabled` field to false
- **AND** the snapshot records a released hold until that same reset time
- **AND** the next quota poll does not set `disabled` back to true

#### Scenario: A new reset time can disable again
- **GIVEN** the snapshot records a released hold until one reset time
- **AND** a later poll computes a different future exhausted-window reset time
- **WHEN** the Claude sidecar quota poll runs
- **THEN** codex-lb sets that auth file's `disabled` field to true
- **AND** the stored hold uses the new reset time and is unreleased

### Requirement: Retry a failed disabled update
When the CLIProxyAPI disabled update fails, codex-lb MUST leave that transition uncommitted and MUST retry it on a later successful poll.

#### Scenario: Disable call fails
- **GIVEN** a Claude auth is enabled and a usage window is exhausted with a future reset time
- **AND** the disabled update returns an error
- **WHEN** the Claude sidecar quota poll runs
- **THEN** the snapshot still shows that auth enabled
- **AND** the snapshot does not record a new hold for that auth

#### Scenario: Enable call fails
- **GIVEN** the snapshot records an unreleased hold for a disabled Claude auth
- **AND** the usage window is no longer exhausted
- **AND** the enable update returns an error
- **WHEN** the Claude sidecar quota poll runs
- **THEN** the snapshot still shows that auth disabled
- **AND** the snapshot still records the unreleased hold

### Requirement: Preserve holds when the quota poll is unhealthy
An unauthorized, unreachable, or error quota poll MUST NOT change any CLIProxyAPI `disabled` field and MUST keep the holds already stored on the quota snapshot.

#### Scenario: Auth listing fails
- **GIVEN** the quota snapshot records a hold
- **AND** the CLIProxyAPI auth listing returns an error
- **WHEN** the Claude sidecar quota poll runs
- **THEN** codex-lb does not update any auth file's `disabled` field
- **AND** the stored snapshot still contains that hold

### Requirement: Round-trip owned holds in the quota snapshot
codex-lb MUST persist each owned hold's auth-file name, reset time, and released flag in the Claude quota snapshot JSON, and a snapshot written before this field existed MUST load with no holds.

#### Scenario: Hold survives a snapshot round trip
- **GIVEN** a quota snapshot contains one hold with a name, a reset time, and a released flag
- **WHEN** that snapshot is stored and loaded
- **THEN** the loaded hold has the same name, reset time, and released flag

#### Scenario: Older snapshot JSON loads
- **GIVEN** a quota snapshot JSON has no holds field
- **WHEN** that snapshot is loaded
- **THEN** the loaded snapshot has no holds

### Requirement: Show the Rate limited badge for an owned hold
A Claude auth this poller disabled for an exhausted window MUST be reported with status rate_limited while that hold is unreleased, and the dashboard MUST show the same Rate limited badge used for Codex accounts. An operator pause with no unreleased hold MUST still show the Paused badge.

#### Scenario: Held auth reports rate limited
- **GIVEN** the quota snapshot records an unreleased hold for a Claude auth
- **AND** that auth file is disabled
- **AND** the auth is not a re-auth failure
- **WHEN** the dashboard reads the Claude sidecar accounts
- **THEN** that auth's status is rate_limited
- **AND** that auth remains paused
- **AND** the dashboard badge is Rate limited

#### Scenario: One held auth marks the synthetic account rate limited
- **GIVEN** one Claude auth has an unreleased hold
- **AND** another Claude auth is enabled
- **WHEN** the dashboard reads the Claude sidecar summary
- **THEN** the synthetic account status is rate_limited
- **AND** only the held auth's status is rate_limited

#### Scenario: Released hold does not force rate limited
- **GIVEN** the quota snapshot records a released hold for a Claude auth
- **AND** the auth status is active
- **WHEN** the dashboard reads the Claude sidecar accounts
- **THEN** that auth's status is active

#### Scenario: Operator pause stays paused
- **GIVEN** a Claude auth file is disabled
- **AND** the quota snapshot has no unreleased hold for that auth
- **AND** the auth status is disabled
- **WHEN** the dashboard reads the Claude sidecar accounts
- **THEN** that auth's status is disabled
- **AND** the dashboard badge is Paused
