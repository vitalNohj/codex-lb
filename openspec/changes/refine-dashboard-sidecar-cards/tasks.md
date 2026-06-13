## 1. Dashboard account viewport

- [x] 1.1 Increase `ACCOUNT_CARD_ROW_HEIGHT_REM` to `16` in `account-cards.tsx`.
- [x] 1.2 Update `account-cards.test.tsx` to expect `maxHeight: "calc(2 * 16rem + 1rem)"`.

## 2. CLI Proxy API synthetic card

- [x] 2.1 Rename the Claude synthetic card title to `CLI Proxy API`.
- [x] 2.2 Render one privacy-aware usage panel per sidecar auth account headed by `<email|name> Usage`.
- [x] 2.3 Add a fallback `Claude Usage` panel when no sidecar auth accounts exist but aggregate usage is present.
- [x] 2.4 Remove the Claude synthetic card `Health`, `Quota`, `Models`, and `Requests` metadata rows.
- [x] 2.5 Keep OpenRouter and OmniRoute card health and request rows.
- [x] 2.6 Remove model-count rows from OpenRouter and OmniRoute cards.

## 3. Sidecar summary status

- [x] 3.1 Set the Claude synthetic `display_name` to `CLI Proxy API`.
- [x] 3.2 Derive OpenRouter synthetic `status` as `active` when enabled and configured, else `paused`.
- [x] 3.3 Derive OmniRoute synthetic `status` as `active` when enabled and configured, else `paused`.
- [x] 3.4 Derive OpenRouter synthetic `health_status` with effective settings status semantics so stale `disabled`/`missing_api_key` probe values do not override an enabled and configured sidecar.
- [x] 3.5 Derive OmniRoute synthetic `health_status` with effective settings status semantics so stale `disabled`/`missing_api_key` probe values do not override an enabled and configured sidecar.

## 4. Verification

- [x] 4.1 Add/update backend tests for OpenRouter and OmniRoute synthetic status.
- [x] 4.2 Update frontend tests for the CLI Proxy API card and viewport.
- [x] 4.3 Add/update frontend tests for OpenRouter and OmniRoute card health/model rows.
- [x] 4.4 Add/update backend tests for stale OpenRouter and OmniRoute health values.
- [x] 4.5 Run focused backend and frontend tests.
- [x] 4.6 Validate the OpenSpec change with `--strict`.
