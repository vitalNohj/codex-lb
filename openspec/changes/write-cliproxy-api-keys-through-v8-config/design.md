# Design

## v0 writes are lossy on a v8 config

CLIProxyAPI v8 stores API keys as named groups (`api-keys.<family>: [{name, base-url, keys: [...], <shared fields>}]`). The v0 endpoints work on a flattened legacy list. `persistLocked` saves through `SaveConfigPreserveComments`, and `restoreV8Layout` (`internal/config/config_v8.go`) compares each family's legacy list with the one decoded from disk. When they differ, it rebuilds the whole family with `groupLegacyKeys`, which yields one group per key named `<provider>-<i+1>`. That happens for any change, including the per-entry `PATCH` (`PatchClaudeKey`), so v0 `PATCH` is not a fix. Claude, Gemini, Codex, and xAI entries carry no name field in v0, so the name cannot survive a v0 round-trip either.

The v8 config API (`/v8/management/config/*path`, `handlers/management/config_v8.go`) edits the raw v8 YAML tree. A `PUT` to `api-keys/<family>` replaces that family's list only. The list codex-lb sends is the one it just read, with one field changed, so names, shared fields, per-key fields, and unknown fields survive. The JSON `GET` injects `auth_index` into each key and writes strip it. codex-lb strips it too before it writes.

## Concurrency

From v8.0.32, `GET` returns an `ETag` (sha256 of the file) and a write with `If-Match` gets `412 precondition_failed` when the file changed after the read. codex-lb redoes the edit on a fresh read, for up to four attempts in all, then reports a conflict. Builds that do not send an `ETag` take the write without the check, as before.

## Per-key pins

A non-compat key may override any shared field, `prefix` included (`expandV8Groups`; `config.example.yaml`). An override set to null inherits the group value. A prefix for one key of a multi-key group is therefore written on that key. It lands on the group only when the group has a single key and the key does not already override it. `base-url` is the one field a key cannot override. Changing it for one key of a multi-key group moves that key into its own group, inserted after the original. The new group copies the shared fields and takes a unique `<group>-<n>` name. CLIProxyAPI's `auth_index` seed holds no group name, so the key's identity does not change.

An openai-compatibility group is one CLIProxyAPI provider. Its keys allow only `api-key`, `weight`, and `proxy-url`, so the group is the pin unit. Which key serves inside the group is CLIProxyAPI's choice. `routing.session-affinity` keeps one conversation on one key. Its session id takes the client's `prompt_cache_key` among other signals (`selector.go`). `support-prompt-cache-key` makes CLIProxyAPI send a stable `prompt_cache_key` upstream (`applyPromptCacheKey`). That is the field OpenAI and OpenRouter use to route related requests to the same cache. The switch stays off by default because it adds a body field that a strict upstream may reject.

## Route identity

CLIProxyAPI derives `auth_index` as `hex(sha256(seed)[:8])` with seed `<seed-kind>:<base-url>+<api-key>` (`sdk/cliproxy/auth/types.go`, `indexSeed`). The seed kind is `openai-compatibility`, `claude-api-key`, `gemini-api-key`, `codex-api-key`, or `xai-api-key`. codex-lb uses the reported value and computes the same digest when it is absent. Prefix, models, name, weight, priority, and the on/off switch are not part of it, so editing them does not orphan a pin. A new key or endpoint is a new credential and gets a new identity.
