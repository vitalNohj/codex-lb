## Why

A CLIProxyAPI Claude auth whose 5h or weekly window is at 0% remaining still has `disabled=false`. CLIProxyAPI keeps offering it, and the request fails upstream even though the dashboard already knows when that window resets. The reset time is the retry window. Native Codex accounts already leave rotation until their own reset, so this change does not touch them.

## What Changes

- On each Claude quota poll, when a usage window reports remaining percent at or below 0 and a reset time still in the future, set that auth file's `disabled` field until the later of those reset times, then clear `disabled` once the window is no longer exhausted.
- Remember which pauses this poller owns inside the existing quota snapshot, so a restart does not resume an operator pause or leave an automatic pause in place after the reset.
- An operator pause is left alone, including a pause that lands while a poll is fetching usage. An explicit Pause drops an owned hold so a later poll does not enable the auth when the window recovers. An explicit Resume during a hold stays resumed for that same reset time, including when the snapshot has no usage reading, so the next poll does not immediately disable the auth again.
- A poll with no usage reading keeps an unreleased hold until its stored reset, then enables the auth. A healthy poll that omits a held auth keeps that hold.
- A failed disable or enable call is not recorded as done. The next poll retries it.
- No live probe, no fixed 300s wait, and no Codex selector or reset-button changes.

## Capabilities

### New Capabilities

- `cliproxy-exhausted-auth-hold`: Disable a CLIProxyAPI Claude auth while a usage window is exhausted, and enable it again at that window's known reset.

### Modified Capabilities

## Impact

- Affected specs: `cliproxy-exhausted-auth-hold`
- Affected backend code: `app/modules/claude_sidecar/quota.py`, `app/modules/claude_sidecar/quota_poller.py`, `app/modules/claude_sidecar/service.py`, and a new hold planner module under `app/modules/claude_sidecar/`
- No migration. Holds live in the quota snapshot JSON.
- No dashboard layout change. A held auth uses the existing Rate limited badge. Resume stays available while the auth is disabled. An operator pause still shows Paused.
- Codex account selection, reset credits, and the sidecar auth-unavailable cooldown stay as they are.
