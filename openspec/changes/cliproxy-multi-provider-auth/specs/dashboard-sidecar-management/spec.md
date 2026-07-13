# dashboard-sidecar-management (delta)

## ADDED Requirements

### Requirement: Install provider adapters before widening CLIProxyAPI auth ingestion

codex-lb MUST introduce a CLIProxyAPI provider-adapter registry and MUST gate Anthropic OAuth usage attachment and Claude-shaped usage estimation behind the Claude adapter before (or in the same atomic change as) removing Claude-only auth-file filters. Widening ingestion without those gates is forbidden.

#### Scenario: Non-Claude auth never triggers Anthropic OAuth

- **GIVEN** the quota snapshot includes a non-Claude CLIProxyAPI auth with an `auth_index`
- **WHEN** the quota poller attaches live usage
- **THEN** codex-lb does not call the Anthropic OAuth usage endpoint for that auth
- **AND** only the Claude adapter may invoke Anthropic OAuth usage

#### Scenario: Adapter registry exists before non-Claude rows are shown

- **GIVEN** CLIProxyAPI returns Claude and Grok/xAI auth files
- **WHEN** multi-provider ingestion is enabled in a deployed build
- **THEN** each auth is classified by a provider adapter
- **AND** observation fields for that auth come from its adapter, not from Claude-only defaults applied to every row

### Requirement: Ingest all CLIProxyAPI auth files with a usable name

codex-lb MUST ingest every CLIProxyAPI Management API auth-file entry whose `name` is a non-empty trimmed string into the CLIProxyAPI quota snapshot and routing account list, and MUST NOT drop entries solely because `provider` or `type` is not Claude. Entries without a usable `name` MUST be skipped. For each ingested entry, codex-lb MUST set a normalized `provider` key (`claude`, `xai`, `unknown`, or a documented alias from spike notes).

#### Scenario: Claude and Grok auth files both appear

- **GIVEN** CLIProxyAPI returns a Claude OAuth auth file and an xAI/Grok OAuth auth file, each with a usable `name`
- **WHEN** the quota snapshot and routing list are built
- **THEN** both auth files are present
- **AND** each exposes `name`, optional `authIndex`, optional email/label, `priority`, paused/disabled state, and normalized `provider`

#### Scenario: Empty-name auth file is skipped

- **GIVEN** CLIProxyAPI returns an auth-file entry with blank or missing `name`
- **WHEN** ingestion runs
- **THEN** that entry is omitted from snapshot and routing lists

#### Scenario: Unknown provider is retained

- **GIVEN** an auth file with usable `name` and unrecognized provider/type fields
- **WHEN** ingestion runs
- **THEN** the entry is retained with normalized `provider` of `unknown`
- **AND** pause and priority controls remain available for that `name`

### Requirement: Expose observation contract fields on CLIProxyAPI auth summaries

codex-lb MUST include `provider`, `quota_windows`, and `supports_manual_plan` on each CLIProxyAPI auth account summary returned to Dashboard/Accounts consumers (`SidecarAuthAccount` or equivalent). `quota_windows` MUST be an ordered list containing only `"five_hour"` and/or `"weekly"` as declared by that auth's adapter. Usage estimate builders MUST NOT populate five-hour live/estimate values for an auth whose `quota_windows` omits `"five_hour"`.

#### Scenario: Claude auth declares both windows

- **GIVEN** a Claude CLIProxyAPI auth with the Claude adapter
- **WHEN** the auth summary is produced
- **THEN** `provider` is `claude`
- **AND** `quota_windows` includes `five_hour` and `weekly`
- **AND** `supports_manual_plan` is true

#### Scenario: Grok auth omits undeclared five-hour estimates

- **GIVEN** a Grok/xAI CLIProxyAPI auth whose adapter declares no `five_hour` window
- **WHEN** usage estimates are built for that auth
- **THEN** five-hour remaining/used/budget fields are not populated as if Claude 5h math applied
- **AND** `quota_windows` does not include `five_hour`

#### Scenario: Manual-only adapter still supports plans

- **GIVEN** a non-Claude auth whose adapter cannot derive live usage
- **WHEN** the auth summary is produced
- **THEN** `supports_manual_plan` is true
- **AND** `quota_windows` may be empty until a manual plan supplies estimate windows

### Requirement: Expose provider on the global CLIProxyAPI routing pool

codex-lb MUST expose CLIProxyAPI routing as one global pool spanning all ingested providers, and each routing account in `GET /api/claude-sidecar/routing` MUST include normalized `provider` in addition to `name`, optional `authIndex`, optional email, numeric `priority`, and paused state. Priority and pause updates MUST continue to target auth-file `name` through existing Management API field patches. Strategy MUST remain a single `round_robin` or `fill_first` value with no per-provider strategy override.

#### Scenario: Routing list includes mixed providers with provider field

- **GIVEN** Claude and Grok auth files exist in CLIProxyAPI
- **WHEN** an operator requests `GET /api/claude-sidecar/routing`
- **THEN** both accounts are returned
- **AND** each account includes normalized `provider`

#### Scenario: Priority update works for a Grok auth file

- **GIVEN** a Grok/xAI auth-file `name` exists
- **WHEN** an operator updates priority for that `name`
- **THEN** codex-lb PATCHes CLIProxyAPI `auth-files/fields` with that `name` and `priority`
- **AND** the refreshed routing state shows the updated priority

#### Scenario: Pause update works for a Grok auth file

- **GIVEN** a Grok/xAI auth-file `name` exists
- **WHEN** an operator pauses or resumes that account
- **THEN** codex-lb PATCHes `disabled` for that `name`
- **AND** Dashboard/Settings reflect the new paused state

#### Scenario: Strategy remains global

- **GIVEN** mixed-provider auth files exist
- **WHEN** an operator sets strategy to `fill_first` or `round_robin`
- **THEN** only the single CLIProxyAPI routing strategy endpoint is updated

### Requirement: Keep auth plans as an additive array keyed by identity and provider

codex-lb MUST keep CLIProxyAPI auth plans persisted as a JSON array and MUST allow an optional `provider` field on each plan row so Claude and non-Claude plans do not clobber each other. Existing Claude plan rows without `provider` MUST continue to match Claude auths. Non-Claude manual plans in this change MUST use `custom` plan typing and MUST only require token budgets for windows that apply to that auth's adapter (no forced fake five-hour budget when `five_hour` is absent).

#### Scenario: Legacy Claude plan without provider still matches

- **GIVEN** a stored auth plan with Claude identity fields and no `provider`
- **AND** a Claude auth with matching identity exists
- **WHEN** estimates are built
- **THEN** the legacy plan still applies to that Claude auth

#### Scenario: Grok custom plan does not overwrite Claude plan

- **GIVEN** a Claude auth plan and a Grok auth plan for different identities (or same identity disambiguated by `provider`)
- **WHEN** plans are saved and estimates are built
- **THEN** each auth receives only its matching plan
- **AND** Claude plan budgets are unchanged by the Grok save

#### Scenario: Weekly-only manual plan does not require five-hour budget

- **GIVEN** a Grok auth whose `quota_windows` omit `five_hour`
- **WHEN** an operator saves a custom manual plan for that auth
- **THEN** validation does not require a five-hour token budget solely to satisfy Claude custom-plan rules

### Requirement: Avoid blended multi-provider parent aggregate usage

When the synthetic CLIProxyAPI parent account's `sidecar_auths` include more than one distinct normalized `provider`, codex-lb MUST NOT expose a blended parent `usage` aggregate that presents mixed-provider remaining percents as a single Claude-shaped 5h/weekly quota. Per-auth cards remain the source of truth for mixed-provider deployments.

#### Scenario: Mixed-provider parent omits blended usage

- **GIVEN** sidecar auth rows include both `claude` and `xai` providers
- **WHEN** the synthetic CLIProxyAPI `AccountSummary` is built
- **THEN** parent `usage` is omitted or null rather than a blended Claude-shaped aggregate
- **AND** per-auth rows still carry their own estimate fields

#### Scenario: Claude-only parent aggregate preserved

- **GIVEN** all sidecar auth rows are Claude
- **WHEN** the synthetic summary is built
- **THEN** existing Claude parent aggregate usage behavior may remain

### Requirement: Prefer same-provider usage-queue correlation for Account labels

When resolving CLIProxyAPI request-log Account labels from usage-queue events within the existing proximity window, codex-lb MUST prefer a usage event whose `provider` matches the request's known CLIProxyAPI upstream provider when such an event exists in the candidate set. The operator-facing Account label MUST remain `CLIProxyAPI: <account>` when a label is known and `CLIProxyAPI` on miss, with no Claude/Grok qualifier in the Account text.

#### Scenario: Prefer matching provider under concurrent mixed traffic

- **GIVEN** two usage events fall in the correlation window, one Claude and one Grok
- **AND** the request is known to be a Grok/CLIProxyAPI-routed Grok model request
- **WHEN** account label correlation runs
- **THEN** the Grok usage event is preferred over the Claude event
- **AND** the Account label is `CLIProxyAPI: <grok account label>` without a Grok qualifier

#### Scenario: Correlation miss stays bare CLIProxyAPI

- **GIVEN** no usage event matches within the window
- **WHEN** request logs are listed
- **THEN** the Account label is `CLIProxyAPI`

#### Scenario: Claude correlated label shape unchanged

- **GIVEN** a Claude CLIProxyAPI request correlates to `claude-user@example.com`
- **WHEN** request logs are listed
- **THEN** the Account label is `CLIProxyAPI: claude-user@example.com`
- **AND** the label does not contain `Claude` as a qualifier

### Requirement: Keep one CLIProxyAPI integration for multi-provider routing configuration

codex-lb MUST route Grok/xAI and future CLIProxyAPI-provider models through the existing CLIProxyAPI sidecar settings (base URL, API key, management key, prefixes, full-models, shared effort override) and MUST NOT require a second External Integrations entry for the same CLIProxyAPI instance. The internal sidecar resolver provider id for this integration MUST remain the existing CLIProxyAPI integration id (`claude`) for this change.

#### Scenario: Grok model uses CLIProxyAPI sidecar settings

- **GIVEN** CLIProxyAPI sidecar routing is enabled
- **AND** prefixes or full-models include a Grok/xAI model id
- **WHEN** a client sends chat-completions for that model
- **THEN** dispatch uses the existing CLIProxyAPI sidecar path
- **AND** no separate Grok integration settings object is required

#### Scenario: Prefix uniqueness still enforced

- **GIVEN** an operator adds a CLIProxyAPI prefix that collides with OpenRouter, OmniRoute, or Ollama
- **WHEN** settings validation runs
- **THEN** the collision is rejected
- **AND** no automatic seed bypasses uniqueness rules

### Requirement: Do not price non-Claude CLIProxyAPI models with Anthropic tables

codex-lb MUST NOT apply Anthropic/Claude reference pricing to non-Claude CLIProxyAPI model ids. When no provider-appropriate price row exists, request-log cost MUST remain `NULL` (not zero).

#### Scenario: Unpriced Grok model stays NULL cost

- **GIVEN** a successful CLIProxyAPI-proxied Grok request with token usage
- **AND** no Grok/xAI price row is configured
- **WHEN** reference cost is computed
- **THEN** cost is `NULL`
- **AND** Claude price aliases are not applied to that model id
