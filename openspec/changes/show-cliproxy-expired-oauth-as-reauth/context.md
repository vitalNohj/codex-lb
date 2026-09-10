# Context

Live failure on 2026-09-07/08: `claude-jvwarrior@gmail.com.json` refresh failed with `invalid_grant` / Refresh token expired. CLIProxyAPI kept listing the file as a routing candidate. Codex-lb's badge mapper only inspected `status_message` and `unavailable`+`unauthorized`. The auth JSON already had `"expired": "2026-09-07T14:05:05Z"` while the dashboard still showed the Max card as usable.

`expired` is the access-token expiry, and it is not a death signal on its own. CLIProxyAPI 7.2.135 renews Claude tokens from a background loop (`sdk/cliproxy/auth/auto_refresh_loop.go`) that becomes due 4 hours before `expired` (`sdk/auth/claude.go` `RefreshLead` returns `4 * time.Hour`). A timestamp a few minutes past due therefore describes a refresh that is pending, already succeeded but not yet flushed to disk, or a sidecar that just restarted - all healthy. Badging those is a false positive.

Nothing upstream, however, converts a lapsed expiry into evidence of death. The 4h figure is a *pre*-expiry scheduling lead; it says nothing about how long a token must be lapsed before the credential is unusable, and no upstream constant expresses such a threshold. A long-lapsed timestamp is equally consistent with a dead refresh token, a stopped or crashed sidecar, an auth removed from the active set, a paused account, clock skew, or a renewed token that was simply never persisted. Expiry age is therefore suggestive but never certain, and codex-lb does not badge on it at any duration.

CLIProxyAPI also reports the failure directly. On a refresh 401 it sets `unavailable=true`, `status=error` and `status_message="unauthorized"`; on a rejected refresh token it sets `status_message="invalid_grant"` (`sdk/cliproxy/auth/conductor_refresh.go`, `conductor_cooldown.go`). It never sets `status` itself to `unauthorized` - `sdk/cliproxy/auth/status.go` has no such value - so the status message carries the signal.

Note that the version-matched management listing (`internal/api/handlers/management/auth_files.go`) does not emit `expired` at all, so the timestamp is read from the auth JSON on disk, `expired`-field only. The refresh token's own validity is never exposed by any field: there is no `refresh_expired`, no refresh-failure counter, and `failed` counts request failures rather than refresh failures.

The `unauthorized` message must be matched exactly. Upstream writes it verbatim on a refresh 401, but its generic failure branch (`applyAuthFailureState`) only fills `status_message` when empty, so a non-401 failure can retain raw upstream text that merely contains the word. Substring matching would badge those transient errors, reopening the hole closed by "harden Claude reauth status mapping".

Known limitation: a refresh-only `invalid_grant` failure does not surface at all. `refreshHTTPError` exposes no `StatusCode()`, so `isUnauthorizedError` misses Anthropic's 400 and the loop's failure branch sets only a 5-minute backoff - leaving the listing `active`, available and message-free until real traffic is attempted. That credential reports as healthy rather than being guessed at.

Quota 429 / cooldown is not re-auth, and it sets `unavailable` too, so `unavailable` alone cannot mean auth death. Pause/`disabled` is not re-auth. Missing `expired` must not invent a badge.
