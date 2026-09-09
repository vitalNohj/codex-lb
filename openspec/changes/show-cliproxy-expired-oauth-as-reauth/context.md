# Context

Live failure on 2026-09-07/08: `claude-jvwarrior@gmail.com.json` refresh failed with `invalid_grant` / Refresh token expired. CLIProxyAPI kept listing the file as a routing candidate. Codex-lb's badge mapper only inspected `status_message` and `unavailable`+`unauthorized`. The auth JSON already had `"expired": "2026-09-07T14:05:05Z"` while the dashboard still showed the Max card as usable.

`expired` is the access-token expiry, and it is not a death signal on its own. CLIProxyAPI 7.2.135 renews Claude tokens from a background loop (`sdk/cliproxy/auth/auto_refresh_loop.go`) that becomes due 4 hours before `expired` (`sdk/auth/claude.go` `RefreshLead` returns `4 * time.Hour`). A timestamp a few minutes past due therefore describes a refresh that is pending, already succeeded but not yet flushed to disk, or a sidecar that just restarted - all healthy. Badging those is a false positive.

Once the expiry is older than that whole refresh window, the loop has demonstrably stopped producing a working token and login is required. That is the label.

CLIProxyAPI also reports the failure directly. On a refresh 401 it sets `unavailable=true`, `status=error` and `status_message="unauthorized"`; on a rejected refresh token it sets `status_message="invalid_grant"` (`sdk/cliproxy/auth/conductor_refresh.go`, `conductor_cooldown.go`). It never sets `status` itself to `unauthorized` - `sdk/cliproxy/auth/status.go` has no such value - so the status message carries the signal.

Note that the version-matched management listing (`internal/api/handlers/management/auth_files.go`) does not emit `expired` at all, so the timestamp is read from the auth JSON on disk, `expired`-field only.

Quota 429 / cooldown is not re-auth, and it sets `unavailable` too, so `unavailable` alone cannot mean auth death. Pause/`disabled` is not re-auth. Missing `expired` must not invent a badge.
