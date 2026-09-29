## 1. Specs

- [x] 1.1 Revise this change and the live `chat-completions-compat` and `api-keys` specs so a routed Claude id is forwarded unchanged
- [x] 1.2 State that price, allowlist, and output bounds exact-match after one `cc/`, `cp-`, or `cp_` prefix

## 2. Wire path

- [x] 2.1 Stop the Claude sidecar profile from renaming the model or reading effort from the model name
- [x] 2.2 Remove Claude version regexes, date peeling, effort peeling, and `claude-` prefix restoration

## 3. Tests

- [x] 3.1 Update pricing, profile, allowlist, dispatch, and discovered-catalog tests for send-through
- [x] 3.2 Validate with `openspec validate --strict` and the focused pytest modules
