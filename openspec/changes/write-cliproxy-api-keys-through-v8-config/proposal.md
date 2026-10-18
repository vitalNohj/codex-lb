# Write CLIProxyAPI API-key accounts through the v8 config API

## Why

codex-lb reads CLIProxyAPI API-key accounts and writes them back through the per-family `/v0/management/<kind>-api-key` endpoints. On a CLIProxyAPI v8 config, every v0 write (`PUT`, `PATCH`, and `DELETE` alike) is converted back into v8 layout by CLIProxyAPI's `restoreV8Layout`. That conversion runs `groupLegacyKeys`, which renames every group in the changed family to `<provider>-<n>` and splits each multi-key group into one group per key. A real CLIProxyAPI v8.0.32 binary confirms it. When codex-lb stored its first sticky prefix on one Claude key, the operator's group names (`my-team-key`, `shared-pool`, `codex-main`) became `claude-1..3` and `codex-1`, and the two-key group split in two.

Three more defects sit on the same path:

- A prefix set for one key of a multi-key group lands on the whole group, so one pin covers several credentials.
- The routing identity of an openai-compatibility group hashed its name, models, and on/off switch. Disabling the group or editing its models moved the identity and orphaned the sticky pin.
- The OpenAI-compatible `support-prompt-cache-key` switch could not be set from codex-lb.

## What Changes

- Read every API-key family with one `GET /v8/management/config/api-keys`, and write one family with `PUT /v8/management/config/api-keys/<family>`. Each write is built from the list just read and sends the read's `ETag` in `If-Match`. On `412`, the edit is redone on a fresh read, up to four attempts.
- Fail closed when the v8 config API is missing. Never fall back to the lossy v0 write.
- Store a prefix (and any shared field) for one key of a multi-key group as a key-level override. Only a `base-url` change splits the key into its own group, named `<group>-<n>`.
- Use CLIProxyAPI's `auth_index` as the route identity. When CLIProxyAPI does not report one (for example, a disabled group), compute the same digest locally: `sha256("<seed-kind>:<base-url>+<api-key>")[:8]`, in hex. An openai-compatibility group is identified by its first key.
- Expose `support-prompt-cache-key` on openai-compatibility accounts, and add a minimal switch for it to the account card. The switch is off by default.

## Capabilities

### New Capabilities

- None

### Modified Capabilities

- `dashboard-sidecar-management`: API-key account writes go through the CLIProxyAPI v8 config API and keep every field. Per-key prefixes, a stable route identity, and the prompt-cache-key switch are added.

## Impact

- Backend: `app/modules/cliproxy_accounts/api_keys.py`, `management.py`, `schemas.py`, `api.py`; `app/modules/proxy/cliproxy_account_routing.py`
- Frontend: one switch and the group label on the CLIProxyAPI API-key account card (`cliproxy-credentials.tsx`, `schemas.ts`)
- Requires CLIProxyAPI with the v8 config API (v8.0.0 or later). `If-Match` is honoured from v8.0.32. Older v8 builds take the write without the check.
- The account id of an openai-compatibility group changes once, from the old name-and-models hash to the `auth_index`. The next prefix sync re-learns it. No migration.
