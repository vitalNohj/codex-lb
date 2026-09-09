# Tasks

## 1. OpenSpec and contracts

- [x] 1.1 Add the frontend-architecture delta for `byApiKey`, `dailyByApiKey`, burst metrics, and the comparison surface.
- [x] 1.2 Run `openspec validate improve-reports-api-key-comparison --strict`.

## 2. Backend aggregations

- [x] 2.1 Add `aggregate_daily_by_api_key` using the same timezone day buckets and report filters as `daily`.
- [x] 2.2 Look up API-key name and prefix; keep null ids and missing-key ids as separate unlabeled buckets.
- [x] 2.3 Roll up `byApiKey` with cost share, tokens, average-day requests, peak day, and burst ratio.
- [x] 2.4 Add repository, service, and integration coverage for bursty vs steady keys and the null-key bucket.

## 3. Reports UI

- [x] 3.1 Parse `byApiKey` and `dailyByApiKey` in the frontend reports schema.
- [x] 3.2 Render the stacked daily chart (top 8 + Other, requests/cost toggle) and sortable comparison table with CSV export.
- [x] 3.3 Add English, Korean, and Simplified Chinese labels.
- [x] 3.4 Keep the comparison section visible when line charts are hidden.
- [x] 3.5 Add frontend unit tests for schema, burst labels, chart folding, table, and page visibility.

## 4. Verification

- [x] 4.1 Run focused backend pytest paths for reports repository, service, and API.
- [x] 4.2 Run focused frontend vitest paths for reports schema, page, and API-key comparison.
- [x] 4.3 Re-run `openspec validate improve-reports-api-key-comparison --strict`.
