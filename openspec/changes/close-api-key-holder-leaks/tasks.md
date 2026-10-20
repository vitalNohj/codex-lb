## 1. Visibility rule

- [x] 1.1 Add `app/modules/api_keys/visibility.py` with the section names, the `reset_credits` section, and one `api_key_visibility` decision that applies the global privacy setting.
- [x] 1.2 Accept `reset_credits` in `usage_sections`; keep the creation default without it.

## 2. Endpoints

- [x] 2.1 `/api/fleet/summary`: no accounts without `account_pool_usage` or with the privacy setting; no email or display name without per-account usage.
- [x] 2.2 `/api/fleet/refresh`: `403` unless the key can view fleet usage.
- [x] 2.3 `/v1/quota-feed`: rows follow the key's visibility; opaque per-key `accountKey`; dashboard unchanged.
- [x] 2.4 `/v1/reset-credit` GET and POST: `403` without `reset_credits`.
- [x] 2.5 Route the OpenCode Go, OmniRoute and chat-provider Responses dispatchers through `_rate_limit_headers_for_request`.
- [x] 2.6 `/v1/usage`: return `expires_at`; no upstream mirror into `limits` when hidden.

## 3. Migration and dashboard

- [x] 3.1 Migration with a single `GRANT_RESET_CREDITS_TO_EXISTING_KEYS` choice (shipped `False`); downgrade keeps the section, because it has no record of which grants it wrote.
- [x] 3.2 Usage-sections picker lists "Reset credits" in the create and edit dialogs, with a hint.

## 4. Tests and docs

- [x] 4.1 Integration tests per endpoint for an unscoped key with no sections and with sections enabled.
- [x] 4.2 Header tests for each Responses dispatcher; migration test; frontend tests.
- [x] 4.3 Update `docs/quota-feed.md` and `docs/api-keys.md`.
