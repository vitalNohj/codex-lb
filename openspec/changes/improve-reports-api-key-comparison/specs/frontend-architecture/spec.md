## ADDED Requirements

### Requirement: Reports API returns per-API-key totals and burst metrics

`GET /api/reports` MUST return `byApiKey` as an array of per-key aggregates for the same filtered window as `summary` and `daily`. Each item MUST include `apiKeyId` (`string` or `null`), `name` (`string` or `null`), `keyPrefix` (`string` or `null`), `costUsd`, `requests`, `tokens`, `percentage` (share of `byApiKey` cost, one decimal), `avgDayRequests` (`requests` divided by the inclusive selected calendar-day count), `peakDayDate` (`YYYY-MM-DD` or `null`), `peakDayRequests`, `peakDayCostUsd`, and `burstRatio` (`peakDayRequests / avgDayRequests` when `avgDayRequests > 0`, else `0`). Rows with `request_logs.api_key_id` null MUST form one bucket with `apiKeyId: null`. A stored `api_key_id` with no matching `api_keys` row MUST keep that id and use `name: null` and `keyPrefix: null`. Items MUST be ordered by `costUsd` descending. Existing `summary`, `daily`, `byModel`, `byAccount`, and `byUseragent` fields MUST keep their current meaning.

#### Scenario: Two keys compare overall volume and burst

- **GIVEN** a 7-day report window
- **AND** key `batch` logged 70 requests on one day and none on the other six
- **AND** key `agent` logged 10 requests on each of the seven days
- **WHEN** `GET /api/reports` is requested for that window
- **THEN** `byApiKey` includes `batch` with `requests=70`, `avgDayRequests=10`, `peakDayRequests=70`, and `burstRatio=7`
- **AND** `byApiKey` includes `agent` with `requests=70`, `avgDayRequests=10`, `peakDayRequests=10`, and `burstRatio=1`

#### Scenario: Null API-key traffic stays a separate bucket

- **WHEN** request logs in the selected window include rows with `api_key_id = NULL` and rows with a real key id
- **THEN** `byApiKey` includes one item with `apiKeyId: null` for the null-backed rows
- **AND** `byApiKey` includes a separate item for the real key id

#### Scenario: Deleted API keys keep their id

- **WHEN** request logs reference `api_key_id="gone"` and no `api_keys` row has that id
- **THEN** `byApiKey` includes an item with `apiKeyId="gone"`, `name: null`, and `keyPrefix: null`

### Requirement: Reports API returns sparse daily-by-API-key rows

`GET /api/reports` MUST return `dailyByApiKey` as the sparse per-key daily series for the selected window. Each item MUST include `date` (`YYYY-MM-DD` in the same timezone local-day buckets as `daily`), `apiKeyId` (`string` or `null`), `requests`, and `costUsd`. Days with no traffic for a key MUST be omitted. The series MUST use the same report filters as `daily`.

#### Scenario: Daily-by-key rows follow local-day buckets

- **WHEN** `GET /api/reports` aggregates two keys that each have traffic on different local days
- **THEN** `dailyByApiKey` contains one row per key per local day that has traffic
- **AND** each row `date` uses `YYYY-MM-DD` in the report timezone

### Requirement: Reports page compares API keys

The `/reports` page MUST render an API-key comparison section from `byApiKey` and `dailyByApiKey` whenever the main reports payload is shown. The section MUST include a stacked daily chart for the selected metric (`req` or `cost`) and a sortable table of every `byApiKey` item. The chart MUST plot at most eight keys plus an `Other` series for the remainder, ranked by the active metric. The table MUST show key identity, requests, cost, tokens, average-day requests, peak day, and burst ratio, and MUST offer a CSV export of those columns. Summary, donut, daily-table, and API-key comparison sections MUST remain visible when line charts are hidden. Changing API-key comparison UI state MUST NOT change Reports filter values or the `GET /api/reports` query.

#### Scenario: Reports shows bursty and steady keys side by side

- **GIVEN** the reports payload includes `batch` with `burstRatio=7` and `agent` with `burstRatio=1`
- **WHEN** `/reports` renders
- **THEN** the API-key table shows both keys
- **AND** `batch` is labeled Burst
- **AND** `agent` is labeled Steady

#### Scenario: Reports folds extra keys into Other on the daily chart

- **GIVEN** `byApiKey` contains nine keys with traffic
- **WHEN** `/reports` renders the API-key daily chart
- **THEN** the chart has eight named key series plus one Other series

#### Scenario: API-key comparison stays visible without line charts

- **GIVEN** the persisted line-chart visibility selection is empty
- **WHEN** `/reports` renders a reports payload that includes `byApiKey`
- **THEN** the API-key comparison section is visible
- **AND** the Cost by Day chart is not rendered

### Requirement: Reports API-key burst labels use fixed thresholds

The `/reports` API-key table MUST classify each key from `burstRatio` as Burst when the ratio is at least `3`, Uneven when the ratio is at least `1.5` and less than `3`, and Steady otherwise. The page MUST label `apiKeyId: null` as `No API key` and a non-null id with null `name` as `Deleted key`.

#### Scenario: Burst thresholds map to English labels

- **WHEN** the table renders keys with `burstRatio` values `1`, `2`, and `4`
- **THEN** the labels are `Steady`, `Uneven`, and `Burst`

#### Scenario: Missing and deleted keys use page-owned labels

- **WHEN** `byApiKey` includes `{ apiKeyId: null }` and `{ apiKeyId: "gone", name: null }`
- **THEN** `/reports` shows `No API key` and `Deleted key`

## MODIFIED Requirements

### Requirement: Reports page renders English user-facing labels

The dashboard SHALL render `/reports` with the following exact page-owned user-facing labels for the current reports surface:

- `Cost Report`
- `Usage history by date range`
- `Loading...`
- `Total Cost`
- `Requests`
- `Cost by Day`
- `Tokens by Day`
- `Distribution by Model`
- `Distribution by UserAgent`
- `Daily Breakdown`
- `API keys`
- `No API key`
- `Deleted key`
- `Other`
- `Burst`
- `Uneven`
- `Steady`
- `Day`
- `Input Tokens`
- `Output Tokens`
- `Cost`
- `Accounts`
- `Total`
- `Failed to load report data:`
- `Failed to load model and user-agent options:`
- `Failed to load account options:`
- `Some report data could not be loaded. Try reloading.`
- `Retry`

Backend-provided strings, account values, model values, API-key names, and raw server error payload text SHALL remain out of scope for this wording change unless `/reports` renders page-owned labels around them.

#### Scenario: Reports page shows English labels

- **WHEN** an authenticated operator opens `/reports` with English as the active locale
- **THEN** the page heading is `Cost Report`
- **AND** the page subtitle is `Usage history by date range`
- **AND** the chart and table section titles include `Cost by Day`, `Tokens by Day`, `Distribution by Model`, `Distribution by UserAgent`, `Daily Breakdown`, and `API keys`
- **AND** the daily table headings include `Day`, `Input Tokens`, `Output Tokens`, `Cost`, and `Accounts`

#### Scenario: Reports page state labels are English

- **WHEN** `/reports` renders a loading, empty, or error state
- **THEN** the loading label is `Loading...`
- **AND** page-owned error wrappers use `Failed to load report data:`, `Failed to load model and user-agent options:`, and `Failed to load account options:` when those failures render
- **AND** the retry warning is `Some report data could not be loaded. Try reloading.`
- **AND** the retry button label is `Retry`
