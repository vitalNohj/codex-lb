## 1. Data and API

- [x] 1.1 Add `api_keys.is_shared` (default false) with a reversible migration.
- [x] 1.2 Accept and return `isShared` on create, update and list; keep `usage_sections` untouched when it changes.

## 2. Visibility

- [x] 2.1 `api_key_is_shared` as the one check in `visibility.py`; `api_key_visibility` grants nothing to a shared key.
- [x] 2.2 Refuse shared keys on reset credits, fleet summary/observability/refresh, quota feed, pooled OAuth usage and warmup.
- [x] 2.3 No quota headers for shared keys.
- [x] 2.4 Own cost and token limits in `/api/codex/usage` `additional_rate_limits`.

## 3. Dashboard

- [x] 3.1 "Shared key" toggle with help tooltip in the create and edit dialogs; sections picker disabled with a note and kept.
- [x] 3.2 "Shared" badge in the key table and APIs list; key info row; en, ko, zh-CN strings.

## 4. Tests and docs

- [x] 4.1 Integration tests per endpoint for a shared key with every section and an unshared key with sections; toggle round-trip.
- [x] 4.2 Migration test; frontend dialog, table and list tests.
- [x] 4.3 Update `docs/api-keys.md` with the toggle and which section enables which capability.
