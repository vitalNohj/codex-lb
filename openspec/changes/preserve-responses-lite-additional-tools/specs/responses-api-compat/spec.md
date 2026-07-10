# responses-api-compat — Delta

## ADDED Requirements

### Requirement: Responses Lite additional_tools input items are preserved

When normalizing Responses or compact request `input`, the service MUST preserve
Codex Responses Lite tool bundles. If any input item has `type` equal to
`additional_tools`, the service MUST leave the entire `input` array and the
top-level `instructions` field unchanged so the Lite prefix (tool bundle plus
adjacent developer instructions) stays in its original wire shape. Separately,
when hoisting instruction messages, the service MUST only hoist items whose
`type` is omitted or `"message"`; any other `system`/`developer`-role input
item MUST be forwarded upstream in its original position and shape.

#### Scenario: additional_tools Lite prefix survives normalization intact

- **WHEN** a Codex client sends a Responses request whose `input` begins with
  `{"type": "additional_tools", "role": "developer", "tools": [...]}` followed
  by a developer instructions message and user content
- **THEN** top-level `instructions` remains unchanged
- **AND** the `additional_tools` item and adjacent developer message remain in
  `input` in their original order

#### Scenario: non-message developer items survive when not Lite-shaped

- **WHEN** a Responses request `input` contains a non-message
  `system`/`developer`-role item (for example `type: "additional_tools"`) and
  no early Lite whole-payload preservation path applies
- **THEN** that non-message item remains in `input` unchanged

#### Scenario: typeless system messages keep hoisting behavior

- **WHEN** an OpenAI-compatible client sends `input` containing
  `{"role": "system", "content": "sys"}` without a `type` field
- **THEN** that item is hoisted into `instructions` as before
