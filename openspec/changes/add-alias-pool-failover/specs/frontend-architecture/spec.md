## ADDED Requirements

### Requirement: Routing settings edit alias pools as ordered target lists

The Routing settings model alias section MUST render each alias as one row whose
target side is an ordered list of target chips. Each row MUST offer: add a
target (text input with a datalist of known model ids), remove a target, and
move a target up or down. Removing the last target MUST be prevented; the row's
`Remove` action deletes the whole alias. The existing Advanced context-length
control MUST remain per alias row. The add-alias form MUST create a one-target
pool. Saves MUST send the whole `modelAliases` map in the pool shape
`Record<string, { targets: string[] }>` through the existing settings autosave
path, and the zod settings schema MUST accept only the pool shape on read.

A settings save rejected by the server pool validation MUST surface the server
message inline on the offending alias row and MUST NOT clear the operator's
unsaved reorder.

#### Scenario: Reorder targets and save

- **GIVEN** `pooled/glm-5.3` shows targets `orcarouter/z-ai/glm-5.3`, `or-z-ai/glm-5.3`
- **WHEN** the operator moves `or-z-ai/glm-5.3` up
- **THEN** the save payload has `modelAliases["pooled/glm-5.3"].targets` equal to `["or-z-ai/glm-5.3", "orcarouter/z-ai/glm-5.3"]`

#### Scenario: Last target cannot be removed

- **GIVEN** an alias row with one target
- **WHEN** the operator looks at the target chip
- **THEN** the chip's remove control is disabled
- **AND** the row-level `Remove` remains enabled

#### Scenario: Server validation error is shown on the row

- **GIVEN** the operator adds `cc/glm-5.3` as a second target
- **WHEN** the server rejects the save because `claude` is not pool-capable
- **THEN** the server message is shown on the `pooled/glm-5.3` row
- **AND** the two-target list remains in the editor

### Requirement: Alias pool target health is visible in Routing settings

While the Routing section is mounted the dashboard MUST poll
`GET /api/settings/alias-pools/health` every 15 seconds and render each target
chip's state: a neutral `healthy` state, or a `cooling` state showing the
expiry time and the last upstream status. The poll MUST stop when the section
unmounts. Health MUST be display-only; it MUST NOT alter the saved pool.

#### Scenario: Cooling chip

- **GIVEN** health reports `orcarouter/z-ai/glm-5.3` as `cooling` with `last_status=402`
- **WHEN** the Routing section renders
- **THEN** the `orcarouter/z-ai/glm-5.3` chip shows a cooling indicator with `402` and the expiry time

#### Scenario: Poll stops on unmount

- **GIVEN** the Routing section is mounted and polling
- **WHEN** the operator collapses the Advanced settings group
- **THEN** no further health requests are issued
