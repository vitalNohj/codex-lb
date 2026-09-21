## 1. Filter key

- [x] 1.1 Add `opencode_go` to the dashboard account-type visibility record, defaulting to visible and filling the key when older preferences omit it.
- [x] 1.2 Classify `provider: "opencode_go"` as that key and label the toggle `OpenCode Go`, placed after OrcaRouter and before OpenAI-compat.
- [x] 1.3 Cover hide/show on the dashboard Accounts section, filter order, and hydration of a preference saved before the key existed.

## 2. Validate

- [x] 2.1 Run `openspec validate toggle-opencode-go-account-filter --strict`.
