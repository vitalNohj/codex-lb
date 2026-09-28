## 1. Identity peel

- [x] 1.1 Add prefix, effort, and release-date peeling in `app/core/usage/model_ids.py` without shortening a model version
- [x] 1.2 Remove the Claude family block from `DEFAULT_MODEL_ALIASES` and resolve prices from the peeled id by exact key

## 2. Wire path

- [x] 2.1 Stop the Claude sidecar wire resolver from rewriting through pricing aliases
- [x] 2.2 Keep effort-suffix peeling, dated wire ids, dotted version normalization, and `claude-` restoration only for an exact price key

## 3. Specs and tests

- [x] 3.1 Sync the main `chat-completions-compat` and `api-keys` specs with this change
- [x] 3.2 Update pricing, profile, allowlist, and discovered-catalog tests for lookalikes and a future catalog id
- [x] 3.3 Validate the change with `openspec validate --strict` and the focused pytest modules
