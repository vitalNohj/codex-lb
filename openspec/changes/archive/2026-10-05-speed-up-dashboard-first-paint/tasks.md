## 1. Overview

- [x] 1.1 Read the conversation raw complement as two `requested_at` ranges
      with an in-statement tail bound; confirm with query plans and the
      conversation parity suite.

## 2. Projections

- [x] 2.1 Add `usage_history_mutation_state`, the SQLite triggers (migration
      and `create_all`), and the generation fast path with digest fallback.
- [x] 2.2 Apply the projection row cap on SQLite with PostgreSQL semantics.
- [x] 2.3 Make aggregate depletion tie-breaking deterministic; prove the
      output no longer varies with `PYTHONHASHSEED`.
- [x] 2.4 Tests: generation fast path, update/delete revalidation, insert
      below the watermark, missing trigger fallback, cap semantics,
      tie-breaking.

## 3. Status bar and timeframe switches

- [x] 3.1 Add `GET /api/dashboard/sync-status` and switch the status bar to it;
      backend and frontend tests.
- [x] 3.2 Keep the previous overview while a new timeframe loads; hook test.

## 4. Test environment

- [x] 4.1 Pre-bundle `react-day-picker` and `date-fns` in Vitest; the
      settings and API-key integration flows pass again.

## 5. Verification

- [x] 5.1 Payload comparison against the previous build at a frozen clock on a
      production snapshot; benchmarks before and after.
- [x] 5.2 Deploy and confirm the dashboard in the browser.
