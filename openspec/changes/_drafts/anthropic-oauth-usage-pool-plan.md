# Anthropic-shaped Claude pool usage endpoint — Execution Plan

**Goal (one sentence):** Expose `GET /api/oauth/usage` that returns Anthropic’s OAuth usage JSON for a single pooled Claude estimate across all accounts, authenticated by API key, without revealing account identity.

**Status:** Draft for review. Do not implement until this plan is approved.

**Public URL (via reverse proxy):** `https://nohj.dev/codex/api/oauth/usage`  
**App route:** `GET /api/oauth/usage`

---

## Locked product decisions (from conversation)

| Decision | Choice |
|---|---|
| Response shape | Anthropic `/api/oauth/usage` body |
| Metric | `utilization` = **used** percent `0–100` (not remaining, not 0–1) |
| Multi-account | One pooled value; no accounts array, no emails, no auth indexes |
| Pool math | Reuse existing `build_claude_usage_estimates(...).aggregate` (budget-weighted remaining → invert to utilization) |
| Extra Anthropic fields | Always include keys: `seven_day_opus`, `seven_day_sonnet`, `extra_usage` as `null` (or minimal stub for `extra_usage` — see open question) |
| Auth | Bearer API key, always required (`validate_usage_api_key`, same as `/v1/usage`) |
| Dashboard endpoint | Leave `/api/claude-sidecar/quota` unchanged |
| Live Anthropic call on request | No — read polled snapshot + usage events already in DB |
| OpenSpec | Required before coding (behavior/API change) |

---

## Open questions for review (resolve before Phase 2)

Answer each before approving implementation:

1. **Paused / disabled auths**  
   Default proposal: **exclude** `disabled`/paused Claude auths from the pool (same idea as native Codex pool skipping paused accounts).  
   - [ ] Approve exclude  
   - [ ] Prefer include paused in pool  

2. **`hide_upstream_quota_from_api_keys`**  
   Default proposal: when that setting is true, return Anthropic body with **`five_hour` / `seven_day` = `null`** (still 200), same spirit as hiding Codex pool on `/v1/usage`.  
   - [ ] Approve hide → null buckets  
   - [ ] Always return pool even when hide is on  
   - [ ] Return 403/404 when hide is on  

3. **`extra_usage` shape**  
   Anthropic sometimes returns an object even when disabled. Default proposal: **`null`** for simplicity.  
   - [ ] Always `null`  
   - [ ] Stub `{ "is_enabled": false, "monthly_limit": null, "used_credits": null, "utilization": null }`  

4. **Sidecar disabled / not configured / no snapshot yet**  
   Default proposal: **HTTP 200** with `five_hour: null`, `seven_day: null`, other keys null (caller-friendly; not an auth failure).  
   - [ ] Approve 200 + nulls  
   - [ ] Prefer 503 / other error  

5. **Error envelope on bad API key**  
   Default proposal: same as other proxy usage routes (`ProxyAuthError` / OpenAI-style auth error), **not** Anthropic error JSON. Auth is ours; body shape is Anthropic only on success.  
   - [ ] Approve  
   - [ ] Prefer Anthropic-looking error body  

---

## Target response contract

### Success (200)

```json
{
  "five_hour": {
    "utilization": 33.0,
    "resets_at": "2026-04-11T07:00:00+00:00"
  },
  "seven_day": {
    "utilization": 13.0,
    "resets_at": "2026-04-17T00:59:59+00:00"
  },
  "seven_day_opus": null,
  "seven_day_sonnet": null,
  "extra_usage": null
}
```

Rules:

- `utilization` = `max(0, min(100, 100 - remaining_percent))` from aggregate.
- Round to one decimal (or leave float as computed — pick one in OpenSpec; propose **1 decimal**).
- `resets_at` = aggregate earliest reset ISO-8601 UTC (same as `ClaudeAggregateUsageEstimate.reset_at_*`), or omit/`null` bucket field if unknown.
- If aggregate remaining is `None` for a window → that window’s bucket is `null` (not `{utilization: 0}`).
- Response MUST NOT include account names, emails, auth_index, confidence, token budgets, or plan types.

### Auth failure

Missing/invalid Bearer → existing proxy auth error path (401).

---

## Not in this plan

- Changing dashboard `/api/claude-sidecar/quota` response.
- Returning per-account Anthropic objects.
- Inventing real `seven_day_opus` / `seven_day_sonnet` / `extra_usage` from local data.
- Calling Anthropic live on each client request.
- Attaching Anthropic ratelimit headers on chat/completions.
- Codex/GPT pool exposure (already `/v1/usage` + `x-codex-*` headers).
- Frontend UI changes (unless a tiny OpenAPI/docs mention is needed — none planned).
- Restarting `codex-lb.service` without operator OK.

---

## Before you start

- [ ] Confirm all open questions above are answered and written into the OpenSpec proposal.
- [ ] Work on a branch from current base: `cloud/<descriptive-name>-e305` under `codex-lb`.
- [ ] Use repo Python: `.venv/bin/python` / `uv run`.
- [ ] Do not restart the shared systemd service unless the user says it is safe.

---

## Files to touch (expected)

| Path | Action |
|---|---|
| `openspec/changes/add-anthropic-oauth-usage-endpoint/` | Create (proposal, specs, tasks, context) |
| `app/modules/claude_sidecar/oauth_usage_response.py` (name flexible) | **Create** — pure mapper: aggregate → Anthropic JSON |
| `app/modules/claude_sidecar/service.py` | Add method e.g. `get_pooled_oauth_usage()` that loads settings + events + builds aggregate |
| `app/modules/proxy/api.py` (or small dedicated router module included from `main.py`) | Add `GET /api/oauth/usage` with `validate_usage_api_key` |
| `app/main.py` | Include router if not already on `usage_router` |
| `tests/unit/test_claude_sidecar_oauth_usage_endpoint.py` (name flexible) | Mapper + HTTP tests |
| Possibly extend `tests/unit/test_claude_sidecar_usage_estimates.py` | Only if pool exclusion of paused needs coverage |

Avoid editing dashboard Claude quota schemas/UI.

---

## Phase 0: OpenSpec (do first — hard gate)

**What this phase achieves:** Normative contract exists and validates before code.

- [ ] Step 0.1: Run `openspec new change "add-anthropic-oauth-usage-endpoint"` from repo root.
- [ ] Step 0.2: Write `proposal.md` with Why / What Changes / Impact matching this plan.
- [ ] Step 0.3: Add delta spec capability (new or extend existing Claude sidecar / proxy usage capability) with MUST/SHALL on the **first sentence** of each requirement (strict parser rule).
- [ ] Step 0.4: Put narrative (Anthropic mirror rationale, pool math, null rules) in `context.md`, not in normative `spec.md`.
- [ ] Step 0.5: Write `tasks.md` checklist aligned to Phases 1–4 below.
- [ ] Step 0.6: Run `openspec validate add-anthropic-oauth-usage-endpoint --strict` and fix until clean.
- [ ] Step 0.7: Commit OpenSpec-only: `docs: add anthropic oauth usage endpoint change`.

**Phase 0 done when:** `openspec validate … --strict` passes and open questions are resolved in writing inside the change.

**Do not start Phase 1 until Phase 0 passes.**

---

## Phase 1: Pure mapper (no HTTP yet)

**What this phase achieves:** Deterministic Anthropic JSON from an aggregate estimate.

- [ ] Step 1.1: Create a small pure function module under `app/modules/claude_sidecar/` (suggested: `oauth_usage_response.py`).
- [ ] Step 1.2: Implement `utilization_from_remaining(remaining: float | None) -> float | None`:
  - `None` → `None`
  - else `clamp(100 - remaining, 0, 100)`
- [ ] Step 1.3: Implement `build_anthropic_oauth_usage_payload(aggregate: ClaudeAggregateUsageEstimate | None) -> dict` returning the five keys listed in the contract.
- [ ] Step 1.4: Map `primary_*` → `five_hour`, `secondary_*` → `seven_day`.
- [ ] Step 1.5: Format `resets_at` as ISO-8601 with timezone (match how other Claude quota APIs serialize datetimes).
- [ ] Step 1.6: Write unit tests:
  - remaining 67 → utilization 33
  - remaining `None` → bucket `null`
  - aggregate `None` → all usage buckets null
  - earliest reset preserved
  - no account fields present
- [ ] Step 1.7: Run `uv run pytest tests/unit/test_<mapper_file>.py` and confirm pass.
- [ ] Step 1.8: Commit: `feat(claude): map pooled estimate to anthropic oauth usage json`.

**Phase 1 done when:** mapper tests pass; no route wired yet.

---

## Phase 2: Service assembly (read existing state)

**What this phase achieves:** One service method that builds the pooled Anthropic payload from DB/settings.

- [ ] Step 2.1: In `ClaudeSidecarService` (or a thin helper used by the route), add `get_pooled_oauth_usage_payload() -> dict`.
- [ ] Step 2.2: Load settings via existing repository (`get_or_create`).
- [ ] Step 2.3: If sidecar disabled / management key missing / no snapshot: return mapper output for `aggregate=None` (unless open question chose errors).
- [ ] Step 2.4: Load usage events for the secondary window (same pattern as `get_quota`: `list_events_since(now - SECONDARY_WINDOW)`).
- [ ] Step 2.5: Call `build_claude_usage_estimates(events=..., plans=..., snapshot=..., now=...)`.
- [ ] Step 2.6: If paused-exclusion approved: filter estimate accounts / snapshot auths so disabled/paused do not contribute (implement at the estimate input or post-filter before `_aggregate` — prefer filtering snapshot accounts + matching events/plans before `build_claude_usage_estimates` to keep one code path).
- [ ] Step 2.7: Pass `estimates.aggregate` into the Phase 1 mapper.
- [ ] Step 2.8: Honor `hide_upstream_quota_from_api_keys` per open-question choice (route may pass a flag into service).
- [ ] Step 2.9: Unit-test service with fake settings/repo/events (no live CLIProxyAPI).
- [ ] Step 2.10: Run those tests; confirm pass.
- [ ] Step 2.11: Commit: `feat(claude): assemble pooled oauth usage payload`.

**Phase 2 done when:** service returns Anthropic dict from fixtures without HTTP.

---

## Phase 3: HTTP route

**What this phase achieves:** Callable `GET /api/oauth/usage` with API-key auth.

- [ ] Step 3.1: Prefer adding the route on `usage_router` in `app/modules/proxy/api.py` **or** a dedicated small router under `claude_sidecar` mounted in `app/main.py` with proxy/OpenAI error format + `validate_usage_api_key`. Pick one place; do not mount twice.
  - Recommendation: dedicated router `prefix=""` route `/api/oauth/usage` next to other proxy usage routes, auth = `Security(validate_usage_api_key)`, to keep Anthropic path out of dashboard session middleware.
- [ ] Step 3.2: Handler returns JSONResponse / Pydantic model that serializes **exactly** the Anthropic keys (snake_case as Anthropic uses — do **not** camelCase this endpoint).
- [ ] Step 3.3: Ensure dashboard router for `/api/claude-sidecar/*` still requires dashboard session and is untouched.
- [ ] Step 3.4: Confirm reverse-proxy `/codex` strip already makes public URL `…/codex/api/oauth/usage` — no nginx change expected; verify by reading existing proxy notes / how `/api/codex/usage` is reached today.
- [ ] Step 3.5: Write HTTP/unit tests with TestClient (or project’s existing API test helpers):
  - no Authorization → 401
  - valid key + fixture aggregate → 200 Anthropic body
  - hide-upstream setting behavior per approved choice
  - sidecar disabled → 200 null buckets (if approved)
- [ ] Step 3.6: Run `uv run pytest` on the new test file(s); confirm pass.
- [ ] Step 3.7: Commit: `feat(proxy): add GET /api/oauth/usage anthropic pool endpoint`.

**Phase 3 done when:** tests prove auth + body contract on the route.

---

## Phase 4: Verify OpenSpec + regression

**What this phase achieves:** Change is ready for review / merge gates later.

- [ ] Step 4.1: Re-run `openspec validate add-anthropic-oauth-usage-endpoint --strict`.
- [ ] Step 4.2: Mark `tasks.md` items complete to match landed work.
- [ ] Step 4.3: Run focused tests: mapper + service + route + `test_claude_sidecar_usage_estimates.py` (aggregate still correct).
- [ ] Step 4.4: Manually (when user OK to hit live instance):  
  `curl -sS -H "Authorization: Bearer <api-key>" https://nohj.dev/codex/api/oauth/usage | jq .`  
  Expect Anthropic keys only; utilization in 0–100; no account fields.
- [ ] Step 4.5: Push branch; open/update PR with `base_branch` = current cloud base; body links OpenSpec change and notes Fixes/Closes only if an issue exists.
- [ ] Step 4.6: Do **not** restart `codex-lb.service` unless user confirms safe.

**Phase 4 done when:** strict OpenSpec clean, focused tests green, PR opened with contract described.

---

## Final verification

- [ ] `GET /api/oauth/usage` requires Bearer API key.
- [ ] Body matches Anthropic field names and `utilization` semantics (used %, 0–100).
- [ ] Single pool only — no per-account leakage.
- [ ] `seven_day_opus` / `seven_day_sonnet` / `extra_usage` present as agreed null/stub.
- [ ] Dashboard `/api/claude-sidecar/quota` unchanged.
- [ ] Pool math uses existing estimate aggregate (OAuth remaining preferred per auth, then weighted).
- [ ] `openspec validate … --strict` passes.
- [ ] Focused pytest green.

---

## If something goes wrong

- [ ] If utilization looks like remaining (e.g. “full” accounts show ~100): you inverted wrong — utilization must be `100 - remaining`.
- [ ] If utilization is `0.33` instead of `33`: you emitted 0–1 scale — multiply/clamp to 0–100.
- [ ] If response is camelCase: wrong serializer / DashboardModel — use plain dict or a dedicated non-aliased model for this route.
- [ ] If 401 with valid proxy key when global auth is off: ensure this route uses `validate_usage_api_key` (always requires key), which is intentional.
- [ ] If numbers flap or empty: poller/snapshot missing — endpoint does not live-fetch; check `claude_sidecar_quota_state_json` / poller health separately.
- [ ] If PR review complains about missing OpenSpec: stop coding features; finish Phase 0 first.

---

## Requirement traceability

| Requirement | Steps |
|---|---|
| Anthropic-shaped body | 1.3–1.6, 3.2, 3.5 |
| Single pooled value, no account details | 2.5–2.7, 1.6, Final verification |
| Path `/api/oauth/usage` (public `/codex/api/oauth/usage`) | 3.1, 3.4 |
| API-key usable from a program | 3.1, 3.5 |
| Reuse estimate/pool math | 2.4–2.7 |
| Do not break dashboard quota API | Phase 3 note, Not in this plan |
| OpenSpec-first | Phase 0 |

---

## Suggested review focus

1. Open questions 1–5 (paused, hide-upstream, extra_usage, empty state, error envelope).
2. Whether null optional Anthropic keys are enough for the consuming client.
3. Whether utilization must be int vs float (Anthropic examples use floats like `33.0`).
4. Confirm no desire for response headers (`anthropic-ratelimit-unified-*`) in this change — out of scope above.
