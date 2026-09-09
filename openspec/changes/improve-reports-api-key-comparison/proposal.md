# Change: Improve Reports API-key comparison

## Why

Reports can already filter by API key, but the page still aggregates those keys into one pile. Operators cannot tell which key (which process) used more overall versus which one spiked on a few days. Per-key totals, a share breakdown, and a burst-versus-steady comparison belong on the Reports tab.

## What Changes

- `GET /api/reports` returns `byApiKey` totals plus burst metrics (average day, peak day, peak/average ratio) and a sparse `dailyByApiKey` series.
- The Reports page renders an always-visible API-key comparison section: stacked daily chart and sortable table.
- Null `api_key_id` rows stay a separate bucket. Deleted keys keep their id with a deleted label.
- Existing summary, daily, model, user-agent, and account aggregations stay unchanged aside from the additive payload fields.

## Capabilities

### Modified Capabilities

- `frontend-architecture`: require per-API-key report aggregates, burst metrics, and the Reports comparison surface.
