# Context

Live failure on 2026-09-07/08: `claude-jvwarrior@gmail.com.json` refresh failed with `invalid_grant` / Refresh token expired. CLIProxyAPI kept listing the file as a routing candidate. Codex-lb's badge mapper only inspected `status_message` and `unavailable`+`unauthorized`. The auth JSON already had `"expired": "2026-09-07T14:05:05Z"` while the dashboard still showed the Max card as usable.

`expired` is the access-token expiry. While it is still in the future, requests can succeed even if refresh is already dead. Once it is in the past and refresh cannot rotate it, login is required. That is the label.

Quota 429 / cooldown is not re-auth. Pause/`disabled` is not re-auth. Missing `expired` must not invent a badge.
