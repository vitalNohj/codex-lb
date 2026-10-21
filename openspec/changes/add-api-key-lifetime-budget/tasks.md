## 1. Lifetime window

- [x] 1.1 `LimitWindow.LIFETIME`, PostgreSQL enum migration (SQLite no-op), sentinel `reset_at`.
- [x] 1.2 `limit_windows.py` lifetime case; unknown window raises `ValueError`.
- [x] 1.3 Skip lifetime in the reset sweep and the lazy reset; keep its spend on reset usage.
- [x] 1.4 Backfill a lifetime limit from spend since key creation.
- [x] 1.5 Exhaustion as `402 insufficient_quota` with no reset time; `reset_at: null` on every reader.

## 2. Budget leaks

- [x] 2.1 Shared key with a cost limit refuses an unpriced model, with the route's own price check.
- [x] 2.2 Charge the reservation of a stream abandoned after it started (Codex HTTP/WebSocket, CLIProxyAPI chat and native Responses).

## 3. Dashboard

- [x] 3.1 "One-time (never resets)" window option and labels; nullable `resetAt`; en, ko, zh-CN.

## 4. Tests and docs

- [x] 4.1 Integration tests: never resets, backfill, exhaustion, self-view, reset usage, unpriced refusal and its exemptions, abandoned-stream charge.
- [x] 4.2 Migration round trip; unit and frontend tests.
- [x] 4.3 `docs/api-keys.md` one-time budgets; `docs/model-pricing.md` exception.
