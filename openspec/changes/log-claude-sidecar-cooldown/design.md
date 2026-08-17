## Context

CLIProxyAPI treats transient 502/`Overloaded` (and 429) as credential cooldown (~1 minute). Follow-up calls return HTTP 503 with `auth_unavailable: no auth available (providers=claude, model=…)`.

codex-lb used to store that string as `claude_sidecar_error` and return it immediately. Dashboard looked like missing auth. Kodus BYOK wraps every generate, records each HTTP failure, and emails at 5 errors / 15 minutes (then 1h notify cooldown). Live `Kodus-LightingTrendz` at 14:45 UTC: 2 Overloaded + 6 auth_unavailable in ~30s → email with sample `auth_unavailable`.

## Decisions

1. Detect cooldown via `auth_unavailable` or `no auth available` in the sidecar message. Do not match generic `unavailable`. Do not retry `Overloaded`.
2. Retry the sidecar call for `CLAUDE_SIDECAR_COOLDOWN_WAIT_SECONDS` (75s). Probe sleeps start at `CLAUDE_SIDECAR_COOLDOWN_RETRY_SLEEP_SECONDS` (2s) and double up to the wait budget. Constants, not a new setting.
3. Share one process-wide `cooldown-until` + single poller. Extra waiters park; they must not fail-fast (a locked-semaphore reject re-emits the Kodus 503 burst). HTTP stays off the lock so healthy traffic is not serialized.
4. If a retry succeeds, persist one **success** request log. Do not write a log row per 503 attempt.
5. If the budget expires, persist `error_code=claude_sidecar_cooldown` / `error_message=Claude sidecar cooldown for <model>` / original text on `failure_detail`, and return the original sidecar envelope once.
6. Stream: retry only before any SSE bytes are yielded. Mid-stream failures stay terminal. Recreate the DeepSeek stream recorder (and reset usage/completed) at the start of each attempt so a failed probe cannot commit into the retry.
7. Do not change CLIProxyAPI `disable-cooling` / `max-retry-interval`. Cooldown stays; we wait it out instead of fail-fast to BYOK counters.

## Risks and Mitigations

- **True empty auth pool** uses the same sidecar string → Mitigation: wait 75s then one 503. Common live case is cooldown.
- **Client timeout during wait** → Mitigation: 75s is under the 600s sidecar request timeout; stream keepalives fire while the iterator sleeps. Kodus code-review generates are non-stream `doGenerate()` and run for minutes.
- **Sidecar wording drift** → Mitigation: match both `auth_unavailable` and `no auth available`.
- **Thundering herd** → Mitigation: shared until + one probe at a time; extras park until that until or a successful probe. Do not fail-fast extras.

## Verification

- Unit-test the log mapper, retry helper (transient cooldown vs Overloaded), exponential backoff, and single-flight parking.
- Integration-test: permanent cooldown still 503 + cooldown log; one 503 then success → 200 and one success log (non-stream and stream).
- `openspec validate log-claude-sidecar-cooldown --strict`.
