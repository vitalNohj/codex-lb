## ADDED Requirements

### Requirement: Public Claude capability metadata shares the existing refresh
The service SHALL retain validated Anthropic input modalities and positive integer context/output limits from the existing models.dev fetch. It SHALL perform no additional remote fetch for these capabilities. Lookup SHALL use the id forwarded by the sidecar route, remove at most one leading `cc/`, `cp-`, or `cp_` routing prefix, and otherwise match the exact model id without family, dotted-version, date, or effort folding.

#### Scenario: A newly released exact id gains metadata
- **WHEN** models.dev lists `anthropic.models.claude-fable-5-2` with text, image, and pdf input, context 1000000, and output 128000
- **THEN** capability lookup for `claude-fable-5-2`, `cc/claude-fable-5-2`, `cp-claude-fable-5-2`, and `cp_claude-fable-5-2` returns that metadata
- **AND** unlisted dotted, dated, effort-suffixed, and double-prefixed spellings do not inherit it

### Requirement: Claude sidecar advertisements use catalog input modalities
For a Claude sidecar model with valid public catalog input modalities, `GET /v1/models` SHALL advertise those modalities and derive its image/vision flags from membership of `image`. Without such metadata, the existing provider-row and known-model fallback behavior SHALL remain unchanged. Limits alone SHALL NOT imply image support.

#### Scenario: A future model advertises image and pdf input
- **WHEN** CLIProxyAPI lists `claude-fable-5-2` without modality metadata and the public catalog declares text, image, and pdf input
- **THEN** its bare and routing-prefix alias rows advertise all three input modalities
- **AND** all advertised image/vision flags are true

#### Scenario: An unknown model keeps its prior advertisement
- **WHEN** neither the public catalog nor the provider row declares modalities for an unknown Claude id
- **THEN** it advertises text-only input and false image/vision flags

### Requirement: Catalog output bounds supplement fixed Claude bounds
A Claude sidecar id without fixed bounds SHALL use valid catalog output/context limits as its cap/context window and retain the 32768 output floor. Fixed rows SHALL retain precedence. Absent limits and deliberate output caps of at most 16 SHALL remain unchanged. Existing context-headroom and client-limit guards SHALL apply unchanged.

#### Scenario: A new release gets the existing floor and its own cap
- **WHEN** `claude-fable-5-2` has no fixed row but has catalog output 128000 and context 1000000
- **THEN** a client output limit of 4096 is raised to 32768, subject to context headroom
- **AND** a client limit above 128000 is clamped to 128000
- **AND** an absent limit and a keep-warm limit of 1 remain unchanged

#### Scenario: Catalog data cannot override a fixed row
- **WHEN** the catalog disagrees with the fixed limits for `claude-fable-5-1`
- **THEN** dispatch retains the fixed 32768 floor, 128000 cap, and 1000000 context window

#### Scenario: Missing or malformed catalog limits keep forwarding unchanged
- **WHEN** an id has no fixed row and no valid pair of catalog output/context limits
- **THEN** its client output limit is forwarded unchanged

### Requirement: Capability metadata retains safe offline behavior
The service SHALL persist last-good capabilities with pricing metadata, retain them across failed or partial refreshes, and restore them after restart. A newer bundled entry SHALL precede an older cached entry. Missing capability metadata in legacy caches or bundles SHALL be accepted and SHALL retain existing model behavior. Invalid metadata SHALL NOT replace valid fields.

#### Scenario: An outage after refresh keeps the known release usable
- **WHEN** a successful refresh learns a Claude model and a later fetch fails or omits its metadata
- **THEN** its last-good capabilities remain available, including after an offline restart

#### Scenario: Bundle generation retains capability metadata
- **WHEN** the existing metadata generator refreshes a bundled snapshot
- **THEN** it retains validated Claude capabilities from its existing models.dev payload without another fetch
- **AND** absent or malformed fields do not erase last-good bundled capabilities

#### Scenario: First startup is offline with a legacy bundle
- **WHEN** no usable capability cache exists and the bundled snapshot has no capability metadata
- **THEN** fixed models keep their prior behavior and unknown models receive no inferred vision support or output bounds
