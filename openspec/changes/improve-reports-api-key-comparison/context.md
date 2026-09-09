# Context: Improve Reports API-key comparison

## Purpose

Give operators a first-pass way to compare API keys on the Reports tab: who used more overall, and who used more in bursts.

## Burst metric

`burstRatio = peakDayRequests / avgDayRequests`, where `avgDayRequests` is `totalRequests / windowDays` and `windowDays` is the inclusive selected calendar range (zero-traffic days count). A weekly batch that spends its whole window on one day scores near `windowDays`; a key that is even across the window scores near `1`.

Pattern labels (UI only, derived from `burstRatio`):

- `burst` when ratio >= 3
- `uneven` when ratio >= 1.5
- `steady` otherwise

Peak-day ties keep the latest calendar date. A one-day range always scores `1` when the key has traffic.

## Daily series

`dailyByApiKey` is sparse: only days with traffic for that key. The same timezone local-day buckets as `daily`. The stacked chart zero-fills the selected range on the client and folds keys after the top 8 (by the active metric) into `Other`.

## Out of scope

- Hourly burst windows
- Per-key previous-window deltas
- Rendering the existing unused `byAccount` payload
- Changing report filters or chart-visibility persistence
