## 1. Selection persistence

- [x] 1.1 Do not persist a runtime `blocked_at` when the loaded account row already has `blocked_at` null.

## 2. Reset-credit refresh

- [x] 2.1 Drop the account's in-process rate-limit runtime markers when the forced post-consume refresh clears the persisted block.

## 3. Tests

- [x] 3.1 Cover a waived row whose runtime still holds the pre-reset 429.
- [x] 3.2 Cover the forced refresh calling the runtime clear.
