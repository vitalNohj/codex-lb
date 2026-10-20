# Stop rewriting stored CLIProxyAPI OAuth prefixes

## Why

The capacity router stores a generated prefix on every CLIProxyAPI credential that has none, then routes by `<prefix>/<model>`. CLIProxyAPI's `GET /v0/management/auth-files` listing never returns `prefix` (checked on 8.0.30, 8.0.32 and the 8.0.36 source), even though the auth file stores it. codex-lb therefore read every stored OAuth prefix as empty. Whenever its 60-second in-process memory (`_PREFIX_OVERLAY_SECONDS`) expired, it sent `PATCH /v0/management/auth-files/fields {"prefix": ...}` with the same value again.

A production host logged 1,296 such PATCHes in 24 hours. Each one rewrites an auth file that also holds rotating Claude OAuth tokens. On CLIProxyAPI below 8.0.34 a fields PATCH can race a token refresh and write the old tokens back (router-for-me/CLIProxyAPI#6733), which forces a Claude re-login.

## What Changes

- New `app/modules/claude_sidecar/auth_file.py` holds the path-confined auth-file read that exclusions already used, plus `stored_prefix_for_entry`. The listing's own `prefix` wins when CLIProxyAPI sends one. Otherwise the prefix is read from the file named by the entry's `path`, and only when that path resolves inside the CLIProxyAPI auth directory. Only the `prefix` key is taken from the file.
- `excluded_models_from_auth_file` uses the same reader. Its behaviour is unchanged.
- The quota snapshot parse (`parse_auth_files`) records the on-disk prefix, so routing candidates carry it.
- `_stored_prefixes`, read under the prefix write lock before any write, reads the on-disk prefix (off the event loop). `_fill_empty_prefixes` reuses a stored prefix and sends no PATCH. It writes only a credential whose prefix is empty, once.
- An unreadable auth file behaves as before: the credential gets a generated prefix.

## Out of scope

- Upgrading CLIProxyAPI, auth-file permissions, and any other routing change.

## Impact

- Affected specs: `sticky-session-operations`.
- Backend: `app/modules/claude_sidecar/{auth_file,excluded_models,quota}.py`, `app/modules/proxy/cliproxy_account_routing.py`.
- No migrations, settings, API or frontend changes.
