## 1. Enable

- [x] 1.1 Reproduce: a poll of a mixed listing (two Claude, one xAI) yields no `cliproxy-xai` card on the overview or the accounts list.
- [x] 1.2 Remove `XAI_QUOTA_INTEGRATION_ENABLED` so the poller always lists xAI logins, reads Grok credits, folds usage-queue rows, and plans xAI holds.
- [x] 1.3 Update the tests that pinned the switch off, keeping their intent: queued usage is taken once, and the real-binary unpinned case runs before the first poll.

## 2. Claude unchanged

- [x] 2.1 Prove xAI holds never disable or enable a Claude login, including an operator-paused one.
- [x] 2.2 Bound each Grok credits fetch with its own short timeout and run the fetches a few at a time, so a stalled xAI login does not hold back saving Claude quota.
- [x] 2.3 Run the Claude sidecar, CLIProxyAPI, quota-feed, and routing suites, and the real CLIProxyAPI binary suites.

## 3. Dashboard

- [x] 3.1 Browser-check the xAI card, its windows or "Quota not reported", and the CLIProxy filter against a local build with a stubbed listing.
- [x] 3.2 Show provider quota windows, prepaid credits, or "Quota not reported" on the Accounts page detail for a non-Claude CLIProxyAPI card.
