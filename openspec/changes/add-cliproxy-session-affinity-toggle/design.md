# Design: CLIProxyAPI session affinity toggle

## Context

CLIProxyAPI 7.3.15 stores session affinity at `routing.session-affinity` (default false). The installed management API exposes `GET/PUT /v0/management/routing/strategy` and `GET /v0/management/config` plus `GET/PUT /v0/management/config.yaml`. It does not expose a dedicated session-affinity route. The JSON config uses the key `session-affinity`. A false value is omitted.

codex-lb already reads and writes the routing strategy and per-account pause, priority, and excluded models. Account selection for Claude stays inside CLIProxyAPI.

## Goals / Non-Goals

**Goals:**

- One global boolean the operator can turn on or off from the dashboard.
- The Accounts Claude detail shows it once, above the per-account list.
- The Settings CLIProxyAPI routing panel shows it once, next to Routing strategy.
- Writes go through the CLIProxyAPI management API and leave the rest of the config in place.

**Non-Goals:**

- Per-account affinity.
- TTL, subagent, or weight editors.
- Forwarding client session headers. Affinity keeps using whatever identity CLIProxyAPI already derives.
- Restarting codex-lb or CLIProxyAPI as part of this change.

## Decisions

### Read the parsed config, write the YAML document

`GET /v0/management/config` is the read path. A missing `routing.session-affinity` means false.

The write path downloads `GET /v0/management/config.yaml`, changes only the direct `routing.session-affinity` line, and uploads it with `PUT /v0/management/config.yaml`. A nested `session-affinity` key is not that flag. Replacing the file from the JSON config would drop comments and can rewrite secrets. A dedicated strategy-style route does not exist in this build, and `PUT /config.yaml` has no version or `If-Match` header, so the client reads the file twice and uploads only when both reads match. If they differ, it retries against the newer document. If three read pairs still disagree, it fails and uploads nothing.

If the requested value is already in effect, including a missing key when the requested value is false, the client does not upload. That avoids a needless hot reload.

If `routing` is not a block, the update fails and does not upload.

### One API, two global controls

`GET /api/claude-sidecar/routing` adds `sessionAffinity`. `PUT /api/claude-sidecar/routing/session-affinity` accepts `{ "sessionAffinity": true | false }` and returns the refreshed routing payload. Unhealthy routing states leave `sessionAffinity` null and the switches disabled.

Both screens call that endpoint. Neither screen repeats the switch on an account row.

### Dashboard names stay camelCase

The dashboard field is `sessionAffinity`. The CLIProxyAPI key stays `session-affinity`.

## Risks / Trade-offs

- [YAML read and write are not one transaction] → Change only the affinity line, and skip the upload when the value already matches. A non-block `routing` value fails closed.
- [PUT config.yaml hot-reloads all of CLIProxyAPI config] → The uploaded document is the current file plus that one line. Other keys, including `session-affinity-ttl` and `session-affinity-subagents`, stay as they were.
- [A false flag is omitted from JSON] → The dashboard treats a missing key as false, which matches CLIProxyAPI's default.

## Migration Plan

No data migration. After the dashboard build is served, the switch shows the live flag. The running CLIProxyAPI config is unchanged by deploying this code.

## Open Questions

None.
