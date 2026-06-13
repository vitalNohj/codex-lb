## 1. Shared sidecar connection test hook

- [ ] 1.1 Add `SidecarConnectionProvider` type and `useSidecarConnectionTest(provider)` to `use-settings.ts`.
- [ ] 1.2 Invalidate provider status, `settings/detail`, `accounts`, and `models` queries in `onSettled` so failed tests still refresh Accounts status.
- [ ] 1.3 Refactor `useClaudeSidecar`, `useOpenRouterSidecar`, and `useOmniRouteSidecar` to reuse the shared test mutation.

## 2. Remove duplicate provider badges

- [ ] 2.1 Remove the synthetic-provider badge from `account-list-item.tsx` while keeping the status badge.
- [ ] 2.2 Remove the synthetic-provider badge from the synthetic account detail header.
- [ ] 2.3 Remove OpenRouter/OmniRoute `Models` rows from synthetic list items.

## 3. Accounts connection controls

- [ ] 3.1 Extract synthetic account detail into `synthetic-account-detail.tsx`.
- [ ] 3.2 Render an integration connection status area (connection, base URL, last checked, message).
- [ ] 3.3 Add a manual `Test connection` button wired to `useSidecarConnectionTest(provider)`, disabled while busy or pending.
- [ ] 3.4 Keep the existing Configure link and OmniRoute external link.

## 4. CLIProxyAPI quota estimation in Accounts

- [ ] 4.1 Create `claude-sidecar-quota-estimation.tsx` with the moved plan helpers and editing UI.
- [ ] 4.2 Read discovered auths from `useClaudeSidecarQuota()` and settings from `useSettings()`.
- [ ] 4.3 Save valid plans via `updateSettingsMutation` + `buildSettingsUpdateRequest`.
- [ ] 4.4 Render only on the CLIProxyAPI synthetic detail; not for OpenRouter or OmniRoute.
- [ ] 4.5 Remove the quota estimation section from `claude-sidecar-settings.tsx`.

## 5. Settings save auto-test

- [ ] 5.1 Remove `Test connection` buttons from the three Settings integration sections.
- [ ] 5.2 After a successful save and secret-field clear, run the matching connection test.
- [ ] 5.3 Do not auto-test on Enable toggle or API-key clear.
- [ ] 5.4 Update Settings copy to point operators to Accounts for manual tests.

## 6. Verification

- [ ] 6.1 Update Accounts tests: no provider badges, no OpenRouter/OmniRoute model rows, connection status, manual test, CLIProxyAPI quota editing.
- [ ] 6.2 Update Settings tests: Save triggers provider test, no `Test connection` button, no quota controls.
- [ ] 6.3 Run focused frontend tests and `npm run typecheck`.
- [ ] 6.4 Validate the OpenSpec change with `--strict` and run `openspec validate --specs`.
