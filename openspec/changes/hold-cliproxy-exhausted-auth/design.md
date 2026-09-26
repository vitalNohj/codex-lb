## Context

CLIProxyAPI chooses the Claude auth for a request. codex-lb does not load-balance those auths. The only routing lever codex-lb writes is the auth file `disabled` field, already used by Pause and Resume.

The quota poll already stores each auth's 5h and weekly remaining percent and reset time. An exhausted window still leaves `disabled` false, and a rate-limit message does not set `quota_exceeded`, so CLIProxyAPI keeps selecting that auth. A live "hi" probe would spend the same quota and can itself return 429. The reset time already on the snapshot is the retry window.

Native Codex accounts leave the selector until their own reset. This change does not alter that path.

## Goals / Non-Goals

**Goals:**

- When a Claude auth has a usage window at or below 0% remaining and a reset time in the future, disable that auth until the later such reset, then enable it again.
- Remember pauses this poller owns so a restart does not resume an operator pause or forget an automatic one.
- Honor explicit Resume for that same reset time.
- Retry a failed disable or enable on the next poll.

**Non-Goals:**

- Codex account selection, Codex reset buttons, and reset-credit behavior.
- A background prompt to test whether the window has recovered.
- A fixed 300 second cooldown.
- A new dashboard badge. A held auth is paused, and the existing Resume control applies.
- Changing the sidecar auth-unavailable cooldown.

## Decisions

### D1. Usage windows decide the hold

Each of the 5h and weekly buckets can contribute a deadline only when `remaining_percent` is not null, is at or below 0, and `resets_at` is strictly after the poll time. The hold lasts until the latest deadline. A rate-limit string in `status_message` does not create a hold while either window still has remaining percent. A missing or already-passed reset does not create a hold and does not invent a wait.

Alternative: probe the auth on a timer. Rejected because the probe spends the quota the hold is trying to protect, and the poll already has the reset time.

### D2. Owned holds live on the quota snapshot

`SidecarQuotaSnapshot.rate_limit_holds` stores `{name, until, released}` in the existing quota JSON. There is no new table column. The poll re-reads that JSON under the same lock as Pause, Resume, and exclusion edits before it decides, so a resume that landed during the usage fetch is visible. A fresh CLIProxyAPI listing does not include these holds, so the poller copies them from the stored snapshot.

`released` false means this poller turned the auth off and must turn it back on when the window clears. `released` true means an operator resumed that same reset instant. The next poll must not disable it again until the computed deadline changes.

An auth that is already disabled, with no owned hold, is an operator pause. The poller does not adopt it and does not enable it later.

### D3. Patch only on a transition

The poller calls `PATCH /v0/management/auth-files/fields` only to disable an enabled exhausted auth, or to enable an auth this poller disabled once the window is clear. The lock is held across that rare call and the snapshot write so Resume cannot interleave. If the patch raises `ClaudeSidecarError`, that transition is left uncommitted and the next poll retries it. The rest of the snapshot still saves, so the usage bars keep updating.

An unhealthy poll (unauthorized, unreachable, or error) does not patch `disabled` and copies the previous holds forward.

### D4. Resume marks the current deadline released

`set_account_paused(name, false)` still clears `disabled`. It also records a released hold for the deadline computed from the snapshot's current usage. Pause does not create or remove a hold. A healthy operator pause therefore has no hold, and a released hold is not an automatic resume later.

## Risks / Trade-offs

- A crash after a successful disable patch and before the snapshot commit looks like an operator pause on the next poll, so the auth stays out of rotation until Resume. The auth is not selected while exhausted. The window for that crash is the snapshot write.
- The dashboard shows Paused for an automatic hold. Resume is the control that lets the auth back in before the reset, and the poller will not immediately undo that Resume.
- If the usage fetch fails, the poll keeps the previous buckets. A stored 0% remaining keeps the hold until that stored reset. A stored positive remaining does not create a new hold.
- Rollback is a code rollback. Auths this version disabled stay disabled until an operator resumes them or a future poll with this behavior enables them.

## Migration Plan

No database migration. Snapshots written before this field existed load with no holds. The first healthy poll after deploy disables auths whose stored usage is already exhausted. Operator pauses stay paused.

## Open Questions

None.
