# sticky-session-operations (delta)

## ADDED Requirements

### Requirement: Stored CLIProxyAPI credential prefixes are not rewritten

The capacity router MUST NOT send a fields write for an OAuth credential whose prefix is already stored. It MUST write a generated prefix only for a credential whose prefix is empty. A prefix counts as stored when the auth-files listing carries it, or when the listing omits it and the credential's auth file stores it.

#### Scenario: A listing without prefixes causes no writes

- **GIVEN** a CLIProxyAPI whose auth-files listing omits `prefix`, and an auth file that stores prefix `lb0881c9d437`
- **WHEN** the router fills empty prefixes on several requests, each after the in-process prefix memory expired
- **THEN** the credential routes as `lb0881c9d437/<model>`
- **AND** codex-lb sends no `PATCH /v0/management/auth-files/fields`

#### Scenario: An empty prefix is written once

- **GIVEN** an auth file without a prefix
- **WHEN** the router fills empty prefixes on several requests
- **THEN** codex-lb sends exactly one fields write with a generated prefix
- **AND** later requests route by that prefix without writing again

### Requirement: Auth-file prefix reads stay inside the auth directory

codex-lb MUST read a credential's auth file only when the listing entry's `path` resolves inside the CLIProxyAPI auth directory. It MUST take only the `prefix` key from the file and MUST NOT return or log any other key.

#### Scenario: A path outside the auth directory is not read

- **GIVEN** a listing entry whose `path` resolves outside the CLIProxyAPI auth directory, directly, through `..`, or through a symlink
- **WHEN** codex-lb looks up the credential's stored prefix
- **THEN** the file is not read and the prefix counts as empty
