## Context

ClaudeAuthCard reuses the native `reauth_required` StatusBadge. Mapping lives in `_looks_like_reauth` inside `sidecar_summary.py`. Live incident: CLIProxyAPI marked an auth `unavailable` with `status=error` / `status_message="context canceled"` while Anthropic OAuth usage still returned HTTP 200 — dashboard showed Re-auth required.

## Goals / Non-Goals

**Goals:**
- Require stronger evidence before mapping Claude sidecar auths to `reauth_required`.
- Preserve true auth-death badge behavior (message signals + `unauthorized`).
- Keep UI/badge copy unchanged.

**Non-Goals:**
- New badge variants or visual redesign.
- Changing CLIProxyAPI cooldown/unavailable semantics.
- Adding a Claude re-login button.
- Clearing stuck CLIProxyAPI unavailable state from codex-lb.

## Decisions

1. **Drop `status=error` from the unavailable fallback**  
   Generic `error` includes transient cancel/timeout paths. Mapping those to reauth is the false positive.  
   Alternative rejected: denylist of transient messages — denylist grows forever; status=`error` is the wrong class.

2. **Keep `unavailable` + `status=unauthorized`**  
   CLIProxyAPI uses `unauthorized` for auth rejection even when `status_message` is empty. Narrower than `error`, still catches blank-message auth death covered by existing tests.

3. **Keep existing message substrings**  
   `authentication_error`, `re-authenticate`, `invalid_grant`, and (`oauth` + `expired`) remain authoritative positive signals regardless of status string.

4. **No frontend changes**  
   Badge already keys off `reauth_required`; tightening the mapper is enough.

## Risks / Trade-offs

- [Risk] True auth death reported only as `status=error` with a novel message → Mitigation: message substrings still catch Anthropic/CLIProxy auth envelopes; expand substrings if a new canonical phrase appears in traffic.
- [Risk] Operators see raw `error` instead of reauth for stuck unavailable rows → Acceptable: more honest; ops can inspect `status_message` / auth-files rather than re-login blindly.
