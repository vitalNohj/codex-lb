# Tasks

## 1. Backend

- [x] 1.1 Add a non-raising v8 config call (`CliproxyManagement.config_v8`) that returns status, `ETag`, and body.
- [x] 1.2 Read every API-key family with one v8 `GET`, and write one family with `PUT` plus `If-Match`. Retry the edit on `412`. Fail closed without the v8 API.
- [x] 1.3 Write shared fields for one key of a multi-key group as key overrides. Split the key into its own group only for a `base-url` change.
- [x] 1.4 Route identity is `auth_index`, with the same digest computed locally when CLIProxyAPI does not report it.
- [x] 1.5 Read and write `support-prompt-cache-key` for openai-compatibility accounts.

## 2. Frontend

- [x] 2.1 Show the group name and a prompt-cache-key switch on openai-compatibility account cards.

## 3. Tests

- [x] 3.1 Integration tests with a v8 fake: names and fields survive, per-key prefix, `412` retry, fail closed on a missing v8 API, and identity across edits.
- [x] 3.2 Real-binary tests (`CLIPROXYAPI_BIN`): round-trip a named-group config, write prefixes, form edit, and delete, then diff the whole saved config.
- [x] 3.3 Frontend tests for the switch and the group label.

## 4. Validation

- [x] 4.1 `openspec validate write-cliproxy-api-keys-through-v8-config --strict`.
