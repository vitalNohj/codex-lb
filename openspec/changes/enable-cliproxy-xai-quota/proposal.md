## Why

xAI subscription logins are signed in through CLIProxyAPI, but the dashboard shows no card for them.
The quota poller already knows how to read Grok credits and hold an exhausted xAI login, but a code switch (`XAI_QUOTA_INTEGRATION_ENABLED = False`) kept it Claude-only until rollout.
The stored quota snapshot therefore lists only Claude logins, and the dashboard's CLIProxyAPI provider cards, which are built from that snapshot, have no xAI row.

## What Changes

- Remove the switch. Each CLIProxyAPI quota poll lists Claude and xAI logins, fetches Grok credits for each usable xAI login, folds xAI usage-queue rows into it, and plans xAI holds.
- The dashboard overview and the accounts list show a read-only `CLIProxyAPI xAI` card with each xAI login, its Grok windows, and its prepaid credits. A login with no windows yet reads "Quota not reported". The card sits under the existing CLIProxy account-type filter.
- xAI logins become codex-lb pin candidates for Grok traffic after the first poll lists them.
- Claude behavior does not change. Claude holds, Claude quota, estimates, and the Claude card keep reading only Claude rows, and an xAI hold never disables or enables a Claude login. Each Grok credits fetch has its own 20-second timeout and the fetches run up to four at a time, so a stalled xAI login cannot hold back saving Claude quota for the 600-second sidecar request timeout.

## Capabilities

### New Capabilities

- none

### Modified Capabilities

- `account-quota-presentation`: the dashboard MUST show polled xAI CLIProxyAPI logins on their own provider card.

## Impact

- Backend: `app/modules/claude_sidecar/grok_credits.py`, `app/modules/claude_sidecar/quota_poller.py`.
- Frontend: the Accounts page detail for a non-Claude CLIProxyAPI card lists each login's provider quota windows and prepaid credits, or "Quota not reported", instead of Claude's 5h/weekly plan line.
  The dashboard card and the CLIProxy filter already handle the provider card.
- No API, schema, setting, or migration change.
- Rollback is a revert. The next poll drops the xAI rows, but an xAI login held at that moment stays disabled until an operator resumes it, because the reverted poller no longer releases xAI holds.
