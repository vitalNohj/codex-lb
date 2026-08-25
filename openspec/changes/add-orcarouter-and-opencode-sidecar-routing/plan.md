# OrcaRouter, OpenCode Zen, OpenCode Free — Execution Plan

**Goal (one sentence):** Clone the OpenRouter HTTP integration three times so Settings → External Integrations can route Cursor chat-completions to OrcaRouter, OpenCode Zen, and OpenCode Free without OmniRoute.

**Not in this plan:** Implementing OmniRoute uninstall, `/v1/responses`, Zen `/messages`, MiMoCode, DeepSeek Web, OpenCode Go, combo stacks, quota pollers, pause controls, or restarting `codex-lb.service`.

**Before you start:**

- [ ] Read `openspec/changes/add-orcarouter-and-opencode-sidecar-routing/proposal.md`, `design.md`, and `context.md`. Those files already decided every product question. Do not reopen them.
- [ ] Confirm you are cloning `app/core/clients/openrouter_sidecar.py` (aiohttp). Do not copy `app/core/clients/ollama_sidecar.py`. Do not copy OmniRoute executors.
- [ ] Confirm you will not write the word `sidecar` into any operator-visible label. Tab names, request-log account column, and synthetic account display names are `OrcaRouter`, `OpenCode Zen`, `OpenCode Free`.
- [ ] Confirm you will not seed prefix `opencode/` on OpenCode Free.
- [ ] Confirm you will not restart systemd unless the operator says it is safe.
- [ ] Confirm `AGENTS.md` / `CLAUDE.md` / `CHANGELOG.md` / `docs/` stay untouched.

## Locked names (copy these, do not invent)

| | OrcaRouter | OpenCode Zen | OpenCode Free |
|---|---|---|---|
| Resolver `provider` | `orcarouter` | `opencode-zen` | `opencode` |
| Settings uniqueness name | `OrcaRouter` | `OpenCode Zen` | `OpenCode Free` |
| UI tab label | `OrcaRouter` | `OpenCode Zen` | `OpenCode Free` |
| Card title | `OrcaRouter Integration` | `OpenCode Zen Integration` | `OpenCode Free Integration` |
| Request-log `source` | `orcarouter_sidecar` | `opencode_zen_sidecar` | `opencode_sidecar` |
| `/v1/models` `owned_by` | `orcarouter` | `opencode-zen` | `opencode` |
| Synthetic `account_id` | `orcarouter-sidecar` | `opencode-zen-sidecar` | `opencode-sidecar` |
| Synthetic `provider` | `orcarouter` | `opencode-zen` | `opencode` |
| Dashboard API prefix | `/api/orcarouter-sidecar` | `/api/opencode-zen-sidecar` | `/api/opencode-sidecar` |
| Default base URL | `https://api.orcarouter.ai/v1` | `https://opencode.ai/zen/v1` | `https://opencode.ai/zen/v1` |
| Seeded prefix | `orcarouter/` strip **off** | `opencode-zen/` strip **on** | `oc/` strip **on** |
| User-Agent | `codex-lb/orcarouter-sidecar` | `codex-lb/opencode-zen-sidecar` | `codex-lb/opencode-sidecar` |
| Extra headers | `HTTP-Referer`, `X-Title` | none | none |
| Key required for chat + test | yes | yes | **no** (`Authorization` omitted when empty) |
| Frontend settings id | `orcarouter` | `opencode-zen` | `opencode` |
| DB/API snake_case prefix | `orcarouter_sidecar_` | `opencode_zen_sidecar_` | `opencode_sidecar_` |
| Frontend camelCase prefix | `orcarouterSidecar` | `opencodeZenSidecar` | `opencodeSidecar` |

`SIDECAR_PROVIDER_ORDER` after the change:

```python
("claude", "openrouter", "orcarouter", "opencode-zen", "omniroute", "opencode", "ollama")
```

Python class names follow OpenRouter: `OrcaRouterSidecarClient`, `OpenCodeZenSidecarClient`, `OpenCodeSidecarClient` (Free uses `OpenCode` not `OpenCodeFree` so the source string stays `opencode_sidecar`).

## Clone inventory

Copy these OpenRouter files, then rename symbols:

| OpenRouter source | OrcaRouter dest | OpenCode Zen dest | OpenCode Free dest |
|---|---|---|---|
| `app/core/clients/openrouter_sidecar.py` | `orcarouter_sidecar.py` | `opencode_zen_sidecar.py` | `opencode_sidecar.py` |
| `app/modules/proxy/openrouter_sidecar_dispatch.py` | `orcarouter_sidecar_dispatch.py` | `opencode_zen_sidecar_dispatch.py` | `opencode_sidecar_dispatch.py` |
| `app/modules/openrouter_sidecar/` | `app/modules/orcarouter_sidecar/` | `app/modules/opencode_zen_sidecar/` | `app/modules/opencode_sidecar/` |
| `app/modules/accounts/openrouter_sidecar_summary.py` | `orcarouter_sidecar_summary.py` | `opencode_zen_sidecar_summary.py` | `opencode_sidecar_summary.py` |
| `frontend/src/features/settings/components/openrouter-sidecar-settings.tsx` | `orcarouter-sidecar-settings.tsx` | `opencode-zen-sidecar-settings.tsx` | `opencode-sidecar-settings.tsx` |
| `tests/unit/test_openrouter_sidecar_client.py` | `test_orcarouter_sidecar_client.py` | `test_opencode_zen_sidecar_client.py` | `test_opencode_sidecar_client.py` |
| `tests/unit/test_openrouter_sidecar_dispatch.py` | `test_orcarouter_sidecar_dispatch.py` | `test_opencode_zen_sidecar_dispatch.py` | `test_opencode_sidecar_dispatch.py` |
| `tests/integration/test_openrouter_sidecar_routing.py` | `test_orcarouter_sidecar_routing.py` | `test_opencode_zen_sidecar_routing.py` | `test_opencode_sidecar_routing.py` |
| `tests/integration/test_openrouter_sidecar_dashboard_api.py` | `test_orcarouter_sidecar_dashboard_api.py` | `test_opencode_zen_sidecar_dashboard_api.py` | `test_opencode_sidecar_dashboard_api.py` |
| `frontend/.../openrouter-sidecar-settings.test.tsx` | matching rename | matching rename | matching rename |

Shared files (edit, do not copy): listed in each phase below.

## Column set (repeat for each provider)

Clone `DashboardSettings` OpenRouter columns in `app/db/models.py` around the `openrouter_sidecar_*` block (starts ~line 970):

- `*_enabled` bool default false
- `*_base_url` string
- `*_api_key_encrypted` LargeBinary nullable
- `*_model_prefixes_json` text
- `*_full_models_json` text
- `*_connect_timeout_seconds` float 8.0
- `*_request_timeout_seconds` float 600.0
- `*_models_cache_ttl_seconds` float 60.0
- `*_last_health_status` string nullable
- `*_last_health_message` text nullable
- `*_last_checked_at` datetime nullable
- `*_last_model_count` int nullable
- `*_default_reasoning_effort` string nullable

Seed JSON for prefixes (server default on the prefixes column):

- Orca: `'[{"prefix":"orcarouter/","strip":false}]'`
- Zen: `'[{"prefix":"opencode-zen/","strip":true}]'`
- Free: `'[{"prefix":"oc/","strip":true}]'`

---

## Phase 0: Prove the template still matches

**What this phase achieves:** You know which OpenRouter functions to copy before you duplicate files.

- [ ] Step 0.1: Open `app/core/clients/openrouter_sidecar.py` and note `_headers()`, `list_models_cached()`, chat, and streaming chat. Those four are the clone surface.
- [ ] Step 0.2: Open `app/modules/proxy/openrouter_sidecar_dispatch.py` and note `openrouter_routing_entry`, `load_openrouter_sidecar_config`, `openrouter_sidecar_config_from_settings`, `build_*` payload that calls `set_reasoning_effort_override`, DeepSeek hooks (`deepseek_resolve_scope`, `deepseek_capture_non_streaming`, `deepseek_observe_stream`), `proxy_chat_to_openrouter`, and `OPENROUTER_SIDECAR_SOURCE`.
- [ ] Step 0.3: Open `app/modules/proxy/api.py` at `v1_chat_completions` (~3788) and the `/v1/models` sidecar loop (~3288). You will add three more `load_*_config` / `routing_entries.append` / `if decision.provider ==` / catalog blocks in the same style. Do not add a `/v1/responses` branch.
- [ ] Step 0.4: Open `app/modules/proxy/sidecar_routing.py` line 26. Replace the tuple with the locked order above.
- [ ] Step 0.5: Open `app/db/alembic/versions/20260619_013000_add_ollama_sidecar_dashboard_settings.py`. That file is the migration *shape* (idempotent `if column not in columns` + batch_alter + downgrade drop). Copy that pattern, not OmniRoute migrations.
- [ ] Step 0.6: Run `cd /home/nohj/personal/codex-lb && uv run python -c "from app.db.migrate import *; ..."` or the repo's existing head helper. Confirm the live Alembic head before writing a revision. Last known head: `20260818_000000_backfill_claude_opus_5_sonnet_5_costs`. If a newer head exists, parent that one instead.

**Phase 0 done when:** You can name the OpenRouter function you will rename for routing entry, config load, dispatch, and dashboard test-connection.

---

## Phase 1: Database model + one Alembic revision

**What this phase achieves:** `dashboard_settings` can store all three integrations, all defaulted off.

- [ ] Step 1.1: In `app/db/models.py`, copy the OpenRouter column block three times. Rename prefixes as in the naming table. Keep types identical.
- [ ] Step 1.2: Set SQLAlchemy defaults: enabled false; Orca base URL `https://api.orcarouter.ai/v1`; Zen and Free base URL `https://opencode.ai/zen/v1`; prefixes JSON as the seed strings above; full models `'[]'`.
- [ ] Step 1.3: In `app/core/config/settings.py`, copy the `openrouter_sidecar_*` env-backed fields (~290) three times with the new names and default URLs. Copy the matching `@field_validator` blocks for base URL and prefixes.
- [ ] Step 1.4: Create `app/db/alembic/versions/YYYYMMDD_HHMMSS_add_orcarouter_opencode_zen_opencode_sidecar_settings.py` by copying the Ollama migration. `down_revision` = live head from Step 0.6.
- [ ] Step 1.5: In `upgrade()`, add every new column only if missing. Seed prefixes via `server_default`. Do not backfill existing rows with `enabled=true`.
- [ ] Step 1.6: In `downgrade()`, drop only the new columns. Do not drop OpenRouter/OmniRoute/Ollama columns.
- [ ] Step 1.7: Confirm the Alembic graph is still a single head using the repo Python entry point (not bare `alembic heads`). If you created a second head, stop and merge instead of shipping.

**Phase 1 done when:** Upgrade adds 39 columns (13 × 3) on a DB that already has dashboard settings, and downgrade removes only those columns.

---

## Phase 2: Settings module (all three at once)

**What this phase achieves:** PUT `/api/settings` can persist the three integrations and reject OmniRoute prefix clashes.

Do this as one pass. Missing a field in schemas but present in the model will break GET settings.

- [ ] Step 2.1: In `app/modules/settings/schemas.py`, copy every `openrouter_sidecar_*` field on the response model, the update model, the base-URL normalizer, prefix/full-model validators, API-key normalizer, and the default-reasoning-effort allowlist (~650). Repeat for `orcarouter_sidecar_*`, `opencode_zen_sidecar_*`, `opencode_sidecar_*`.
- [ ] Step 2.2: Default base URLs in schemas must match the naming table.
- [ ] Step 2.3: In `app/modules/settings/service.py`, copy OpenRouter fields on the read dataclass, the update dataclass, encrypt/clear-key handling, `_to_payload` mapping, and `_from_row` mapping.
- [ ] Step 2.4: Free key encrypt/clear stays in code (operator may paste a key later) but configured/active logic in later phases treats empty key as OK.
- [ ] Step 2.5: In `_validate_unique_sidecar_routes`, add `("OrcaRouter", ...)`, `("OpenCode Zen", ...)`, `("OpenCode Free", ...)` to both the prefixes tuple and the full-models tuple.
- [ ] Step 2.6: In `app/modules/settings/repository.py`, copy OpenRouter create-row kwargs, `update()` parameters, and the `if field is not None: settings.field = field` assignments.
- [ ] Step 2.7: In `app/modules/settings/api.py`, copy OpenRouter GET mapping, PUT merge (`model_fields_set` for keys and effort), and the redaction/allowlist field-name lists.
- [ ] Step 2.8: In `app/modules/proxy/sidecar_routing.py`, set `SIDECAR_PROVIDER_ORDER` to the locked tuple.
- [ ] Step 2.9: Extend `tests/unit/test_settings_service.py` helper that builds update payloads. Add the new fields with disabled defaults.
- [ ] Step 2.10: Add a test: saving OpenCode Free `oc/` while OmniRoute already has `oc/` raises `SidecarRoutingConflictError`.
- [ ] Step 2.11: Add a test: saving OrcaRouter `orcarouter/` while OmniRoute already has `orcarouter/` raises the same error.
- [ ] Step 2.12: Add a test: saving OpenCode Zen `opencode-zen/` while OmniRoute already has `opencode-zen/` raises the same error.
- [ ] Step 2.13: Add a test: GET settings redacts API keys and sets `*_api_key_configured` true only when ciphertext exists.
- [ ] Step 2.14: Run `uv run pytest tests/unit/test_settings_service.py -q`. If it fails, fix settings before touching clients.

**Phase 2 done when:** Settings round-trip tests pass and the three OmniRoute overlap tests fail uniqueness on save.

---

## Phase 3: OrcaRouter client + dispatch

**What this phase achieves:** `orcarouter/auto` chat-completions can leave codex-lb toward `api.orcarouter.ai`.

- [ ] Step 3.1: Copy `openrouter_sidecar.py` to `orcarouter_sidecar.py`. Rename config/error/client classes.
- [ ] Step 3.2: Change default comments/URLs to `https://api.orcarouter.ai/v1`.
- [ ] Step 3.3: In `_headers()`, keep Bearer when key present. Set `User-Agent` to `codex-lb/orcarouter-sidecar`. Add `HTTP-Referer` (use `https://github.com/vitalNohj/codex-lb`) and `X-Title` (`codex-lb`). Do not add OmniRoute CLI spoof headers.
- [ ] Step 3.4: Copy `openrouter_sidecar_dispatch.py` to `orcarouter_sidecar_dispatch.py`. Rename every OpenRouter symbol. Set `ORCAROUTER_SIDECAR_SOURCE = "orcarouter_sidecar"`. Set `provider="orcarouter"` on the routing entry.
- [ ] Step 3.5: Keep `set_reasoning_effort_override` and the three DeepSeek V4 hooks. Pass provider token `orcarouter` into DeepSeek scope.
- [ ] Step 3.6: Cost: keep `reference_cost_from_sidecar_usage`. Do not invent Orca per-token prices. Null cost is correct when pricing has no row. `-free` models still go through `is_known_free_model`.
- [ ] Step 3.7: Copy `tests/unit/test_openrouter_sidecar_client.py` and `test_openrouter_sidecar_dispatch.py`. Rename. Add an assertion that `orcarouter/auto` is forwarded unstripped. Add an assertion that headers include Referer + X-Title + the Orca User-Agent. Add an assertion that the API key never appears in error bodies.
- [ ] Step 3.8: Run `uv run pytest tests/unit/test_orcarouter_sidecar_client.py tests/unit/test_orcarouter_sidecar_dispatch.py -q`.

**Phase 3 done when:** Those two unit files pass.

---

## Phase 4: OpenCode Zen client + dispatch

**What this phase achieves:** `opencode-zen/mimo-v2.5-free` strips to `mimo-v2.5-free` and uses a Bearer key.

- [ ] Step 4.1: Copy the Orca/OpenRouter client to `opencode_zen_sidecar.py`. Default base URL `https://opencode.ai/zen/v1`. User-Agent `codex-lb/opencode-zen-sidecar`. Do **not** add Referer/X-Title unless OpenRouter already had them (it does not).
- [ ] Step 4.2: Copy dispatch to `opencode_zen_sidecar_dispatch.py`. Source `opencode_zen_sidecar`. Provider `opencode-zen`.
- [ ] Step 4.3: Keep effort override + DeepSeek V4. Provider token `opencode-zen`.
- [ ] Step 4.4: Missing key: do not send a successful chat. Match OpenRouter's missing-key skip / error path.
- [ ] Step 4.5: Copy unit tests. Assert `opencode-zen/mimo-v2.5-free` → wire `mimo-v2.5-free`. Assert Bearer is set when key present. Assert DeepSeek reinject runs on a tool-turn fixture.
- [ ] Step 4.6: Run `uv run pytest tests/unit/test_opencode_zen_sidecar_client.py tests/unit/test_opencode_zen_sidecar_dispatch.py -q`.

**Phase 4 done when:** Those two unit files pass.

---

## Phase 5: OpenCode Free client + dispatch

**What this phase achieves:** `oc/big-pickle` strips to `big-pickle` with no Authorization header.

- [ ] Step 5.1: Copy the Zen client to `opencode_sidecar.py`. Same default URL. User-Agent `codex-lb/opencode-sidecar`.
- [ ] Step 5.2: In `_headers()`, omit `Authorization` when the key is empty or whitespace. If a key is present, send Bearer (optional-key path).
- [ ] Step 5.3: Copy dispatch. Source `opencode_sidecar`. Provider `opencode`.
- [ ] Step 5.4: Keyless dispatch must actually call upstream. Do not treat missing key as `missing_api_key` on this path.
- [ ] Step 5.5: Copy unit tests. Assert no Authorization header when key is None. Assert `oc/big-pickle` → `big-pickle`. Assert DeepSeek reinject. Assert cost 0 for `oc/big-pickle` via `is_known_free_model`.
- [ ] Step 5.6: Run `uv run pytest tests/unit/test_opencode_sidecar_client.py tests/unit/test_opencode_sidecar_dispatch.py -q`.

**Phase 5 done when:** Those two unit files pass and a captured request has no `Authorization` header.

---

## Phase 6: Wire `/v1/chat/completions` and `/v1/models`

**What this phase achieves:** The resolver can actually select the new providers.

- [ ] Step 6.1: In `app/modules/proxy/api.py` `v1_chat_completions`, import the three clients and `load_*_config` / `*_routing_entry` / `proxy_chat_to_*` helpers.
- [ ] Step 6.2: After the existing `load_openrouter_sidecar_config()` call, load the three new configs.
- [ ] Step 6.3: Append routing entries only when `config is not None and config.enabled`, in an order that matches `SIDECAR_PROVIDER_ORDER` (claude, openrouter, orcarouter, opencode-zen, omniroute, opencode, ollama).
- [ ] Step 6.4: Inside `if decision is not None:`, add explicit `if decision.provider == "orcarouter":`, `"opencode-zen":`, `"opencode":` branches **before** the OmniRoute fallback `assert`. If you leave them to fall through, they will call OmniRoute.
- [ ] Step 6.5: Repeat the load/entry/catalog loop in the `/v1/models` handler. For each enabled integration, iterate `config.full_models`, `resolve_sidecar_route`, skip if provider mismatch, skip if already seen, skip if API-key allowlist hides it, then emit `owned_by` from the naming table.
- [ ] Step 6.6: Do not add these providers to `/v1/responses`.
- [ ] Step 6.7: Copy `tests/integration/test_openrouter_sidecar_routing.py` three times. Cover enabled route, disabled fallthrough, strip vs no-strip, full-model beating an OpenRouter prefix (Orca `openai/gpt-5.5` case), Zen vs Free prefix split (`opencode-zen/mimo-v2.5-free` must not hit Free), and allowlist hiding.
- [ ] Step 6.8: Extend `tests/unit/test_sidecar_routing.py` so a longest-prefix / order tie uses the new tuple.
- [ ] Step 6.9: Run `uv run pytest tests/integration/test_orcarouter_sidecar_routing.py tests/integration/test_opencode_zen_sidecar_routing.py tests/integration/test_opencode_sidecar_routing.py tests/unit/test_sidecar_routing.py -q`.

**Phase 6 done when:** Routing integration tests pass and OmniRoute is not invoked for `orcarouter/auto`, `opencode-zen/mimo-v2.5-free`, or `oc/big-pickle`.

---

## Phase 7: Dashboard APIs

**What this phase achieves:** Settings tabs can test connection and list discovered models.

- [ ] Step 7.1: Copy `app/modules/openrouter_sidecar/` to the three new packages. Rename schemas/status literals the same way OpenRouter does (`disabled`, `missing_api_key`, `unreachable`, `unauthorized`, `healthy`, `error`).
- [ ] Step 7.2: Copy `OpenRouterSidecarContext` / `get_openrouter_sidecar_context` in `app/dependencies.py` three times.
- [ ] Step 7.3: In `app/main.py`, `include_router` the three new routers next to the OpenRouter include (~line 700).
- [ ] Step 7.4: Orca `_classify_static_status`: disabled → `disabled`; no ciphertext → `missing_api_key` and **do not** call the network; else proceed.
- [ ] Step 7.5: Zen: same missing-key skip as Orca.
- [ ] Step 7.6: Free: disabled → `disabled`; enabled with no key → still `healthy` enough to call `GET /models`. `configured` is true when enabled (key optional).
- [ ] Step 7.7: Copy `tests/integration/test_openrouter_sidecar_dashboard_api.py` three times. Cover disabled, unauthorized dashboard session, unreachable upstream, Orca/Zen missing-key (no network), Free keyless success.
- [ ] Step 7.8: Run those three dashboard API test files.

**Phase 7 done when:** Missing Orca/Zen key never hits the network in tests; enabled Free without a key does.

---

## Phase 8: Accounts, request logs, pricing

**What this phase achieves:** Dashboard Accounts and Request Logs show the three names.

- [ ] Step 8.1: Copy `app/modules/accounts/openrouter_sidecar_summary.py` three times. Display names from the naming table. `kind="sidecar"` may stay (internal). `workspace_label` can stay `"External sidecar"` only if OpenRouter already uses that string; do not put `sidecar` in `display_name`.
- [ ] Step 8.2: Free summary: show the account when `enabled` is true even if `api_key_encrypted` is None. Active status may follow enabled, not key.
- [ ] Step 8.3: Orca and Zen summaries: configured/active requires ciphertext, same as OpenRouter.
- [ ] Step 8.4: In `app/modules/accounts/service.py`, append the three synthetics next to the OpenRouter/Ollama block (~247).
- [ ] Step 8.5: In `app/modules/dashboard/service.py`, append the three synthetics next to the OpenRouter/OmniRoute block (~103). Copy the `_build_*_summary` helpers.
- [ ] Step 8.6: Extend `tests/unit/test_sidecar_account_summaries.py` for all three, including Free-without-key visible and Zen-without-key not active.
- [ ] Step 8.7: In `frontend/src/features/dashboard/components/recent-requests-table.tsx`, add the three sources to `SIDECAR_SOURCE_LABELS` and `SIDECAR_ACCOUNT_LABELS`. Values: `OrcaRouter`, `OpenCode Zen`, `OpenCode Free`.
- [ ] Step 8.8: Search backend request-log label maps for `openrouter_sidecar` and add the three sources the same way (repository/service if present).
- [ ] Step 8.9: In `app/core/usage/pricing.py`, add `"opencode-zen/big-pickle"` to `_OPAQUE_FREE_MODELS`. Leave `"big-pickle"` and `"oc/big-pickle"`. Do not add Orca prices.
- [ ] Step 8.10: Add a unit test that `is_known_free_model("opencode-zen/mimo-v2.5-free")` is true via the `-free` regex and `is_known_free_model("opencode-zen/big-pickle")` is true via the allowlist.
- [ ] Step 8.11: In `frontend/src/features/accounts/components/synthetic-account-detail.tsx`, **stop using** `isClaude = !isOpenRouter && !isOmniRoute`. Add explicit branches for `orcarouter`, `opencode-zen`, `opencode`, and `ollama`. Settings hashes: `#orcarouter-sidecar`, `#opencode-zen-sidecar`, `#opencode-sidecar`. Do not show Claude pause or 5h/weekly quota on these cards.
- [ ] Step 8.12: In `sidecar-effort-select.tsx`, add the three `EffortFieldKey`s and `fieldForProvider` branches. Do not fall through to Claude.
- [ ] Step 8.13: In `account-list-item.tsx` / `account-actions.tsx`, add provider name branches so Orca is not labeled Claude.
- [ ] Step 8.14: Run `uv run pytest tests/unit/test_sidecar_account_summaries.py tests/unit/test_request_logs_repository.py -q` plus any pricing test you added.

**Phase 8 done when:** Accounts API can return the three synthetics and Request Logs mapping tests use the locked labels.

---

## Phase 9: Frontend schemas, hooks, MSW

**What this phase achieves:** Typecheck does not explode from missing `.default()` fields.

- [ ] Step 9.1: In `frontend/src/features/settings/schemas.ts`, copy the OpenRouter DashboardSettings fields, SettingsUpdateRequest fields, and the string-union of field names. Repeat three times. Defaults: enabled false; URLs from the naming table; prefixes `[]`; effort schema reused.
- [ ] Step 9.2: Add dashboard response schemas (`OrcaRouterSidecarStatusResponseSchema`, etc.) by copying OpenRouter's.
- [ ] Step 9.3: In `frontend/src/features/settings/payload.ts`, copy the OpenRouter payload mapping three times.
- [ ] Step 9.4: In `frontend/src/features/settings/api.ts`, add paths and `get/post` helpers for `/api/orcarouter-sidecar`, `/api/opencode-zen-sidecar`, `/api/opencode-sidecar` status/models/test.
- [ ] Step 9.5: In `use-settings.ts`, extend `SidecarConnectionProvider` with `"orcarouter" | "opencode-zen" | "opencode"`. Add `SIDECAR_TEST_CONFIG` entries. Toast strings: `OrcaRouter tested` / `OpenCode Zen tested` / `OpenCode Free tested` — no word `sidecar`. Add `useOrcaRouterSidecar`, `useOpenCodeZenSidecar`, `useOpenCodeSidecar`.
- [ ] Step 9.6: Orca/Zen `modelsEnabled: sidecarEnabled && sidecarApiKeyConfigured`. Free `modelsEnabled: sidecarEnabled` only.
- [ ] Step 9.7: Add the new fields to **every** `BASE_SETTINGS` / factory object:

  - `frontend/src/test/mocks/factories.ts`
  - `frontend/src/features/settings/schemas.test.ts`
  - `frontend/src/features/settings/payload.test.ts`
  - `frontend/src/features/settings/components/claude-sidecar-settings.test.tsx`
  - `frontend/src/features/settings/components/openrouter-sidecar-settings.test.tsx`
  - `frontend/src/features/settings/components/omniroute-sidecar-settings.test.tsx`
  - `frontend/src/features/settings/components/ollama-sidecar-settings.test.tsx`
  - `frontend/src/features/settings/components/sidecar-integrations.test.tsx`
  - `frontend/src/features/settings/components/sidecar-integrations-card.test.tsx`
  - `frontend/src/features/settings/components/routing-settings.test.tsx`

  If `bun run build` later errors on a missing key, the fixture you skipped is in that list.
- [ ] Step 9.8: In `frontend/src/test/mocks/handlers.ts`, copy OpenRouter status/models/test handlers three times. Add the three GET/POST paths to `handler-coverage.test.ts`.
- [ ] Step 9.9: Add schema/payload tests that parse a document containing the new fields.
- [ ] Step 9.10: From `frontend/`, run the schema/payload tests. Do not run them from repo root.

**Phase 9 done when:** `npx vitest run src/features/settings/schemas.test.ts src/features/settings/payload.test.ts` passes from `frontend/`.

---

## Phase 10: Settings tabs and conflict IDs

**What this phase achieves:** Operators see three new tabs on the existing External Integrations card.

- [ ] Step 10.1: Copy `openrouter-sidecar-settings.tsx` to the three new files. Keep `bare?: boolean`. Keep enable toggle above the callout (the shared `SidecarIntegrationCard` already does this).
- [ ] Step 10.2: Orca meta: `id: "orcarouter"`, title `OrcaRouter Integration`, conflictName `OrcaRouter`, sectionId `orcarouter-sidecar`. Callout: get a key from OrcaRouter; seed prefix `orcarouter/` is strip-off so `orcarouter/auto` stays namespaced; remove OmniRoute `orcarouter/` first. External link to Orca docs if you have a stable HTTPS URL; `rel="noopener noreferrer"` and new tab.
- [ ] Step 10.3: Zen meta: `id: "opencode-zen"`, title `OpenCode Zen Integration`, conflictName `OpenCode Zen`, sectionId `opencode-zen-sidecar`. Callout: create a key at `https://opencode.ai/docs/zen/`; prefix `opencode-zen/` strips on the wire; remove OmniRoute `opencode-zen/` first. External link opens in a new tab with `rel="noopener noreferrer"`.
- [ ] Step 10.4: Free meta: `id: "opencode"`, title `OpenCode Free Integration`, conflictName `OpenCode Free`, sectionId `opencode-sidecar`. Callout: keyless public `https://opencode.ai/zen/v1`; expect 429/503; do not seed `opencode/`; remove OmniRoute `oc/` first. Keep an optional API-key field (clone Secrets) but do not require it. `modelsEnabled` is enable-only.
- [ ] Step 10.5: In `sidecar-integration-card.tsx`, extend `SidecarIntegrationId` with `"orcarouter" | "opencode-zen" | "opencode"`. Add `INTEGRATION_NAMES` entries. Add three objects inside `integrationValues()`.
- [ ] Step 10.6: In `sidecar-integrations.tsx`, insert three tab objects. Suggested visual order after OpenRouter: OrcaRouter, OpenCode Zen, OmniRoute, OpenCode Free, Ollama — or keep OmniRoute where it is and append the three at the end. Either is fine as long as labels match. Do not add a new card.
- [ ] Step 10.7: Copy `openrouter-sidecar-settings.test.tsx` three times. Cover enable, prefix add, discovered-model add, effort override, test-connection.
- [ ] Step 10.8: Extend `sidecar-integrations-card.test.tsx` / `sidecar-integrations.test.tsx`: tabs exist; default active tab follows the only-enabled integration; OmniRoute `oc/` vs Free `oc/` shows inline conflict; OmniRoute `orcarouter/` vs Orca shows inline conflict; OmniRoute `opencode-zen/` vs Zen shows inline conflict; Free test without key; Zen test without key reports missing key.
- [ ] Step 10.9: From `frontend/`, run those Vitest files.

**Phase 10 done when:** The External Integrations card tests pass and no test still expects only four tabs.

---

## Phase 11: Backend verification

- [ ] Step 11.1: Run `uv run openspec validate add-orcarouter-and-opencode-sidecar-routing --strict`.
- [ ] Step 11.2: Run `uv run pytest tests/unit/test_orcarouter_sidecar_client.py tests/unit/test_orcarouter_sidecar_dispatch.py tests/unit/test_opencode_zen_sidecar_client.py tests/unit/test_opencode_zen_sidecar_dispatch.py tests/unit/test_opencode_sidecar_client.py tests/unit/test_opencode_sidecar_dispatch.py tests/unit/test_sidecar_routing.py tests/unit/test_settings_service.py tests/unit/test_sidecar_account_summaries.py -q`.
- [ ] Step 11.3: Run `uv run pytest tests/integration/test_orcarouter_sidecar_routing.py tests/integration/test_opencode_zen_sidecar_routing.py tests/integration/test_opencode_sidecar_routing.py tests/integration/test_orcarouter_sidecar_dashboard_api.py tests/integration/test_opencode_zen_sidecar_dashboard_api.py tests/integration/test_opencode_sidecar_dashboard_api.py tests/integration/test_settings_api.py tests/integration/test_migrations.py -q`.
- [ ] Step 11.4: Run ruff/lint on the files you touched (`uv run ruff check` on those paths, or the repo's usual local-ci subset).
- [ ] Step 11.5: If a test file you copied still imports OpenRouter names, rename them. Do not leave skipped tests.

**Phase 11 done when:** All commands above exit 0.

---

## Phase 12: Frontend verification

- [ ] Step 12.1: `cd frontend && npx vitest run src/features/settings/components/orcarouter-sidecar-settings.test.tsx src/features/settings/components/opencode-zen-sidecar-settings.test.tsx src/features/settings/components/opencode-sidecar-settings.test.tsx src/features/settings/components/sidecar-integrations-card.test.tsx src/features/settings/components/sidecar-integrations.test.tsx src/features/dashboard/components/recent-requests-table.test.tsx`.
- [ ] Step 12.2: `cd frontend && bun run build`. If it fails on a missing settings field, add that field to the fixture named in the error. Do not weaken the zod schema.
- [ ] Step 12.3: Do not restart `codex-lb.service`. Do not run the full pytest suite unprompted.

**Phase 12 done when:** Vitest subset and `bun run build` pass.

---

## Phase 13: Operator enablement (after merge, not in this PR)

Do not enable the tabs in this change. Defaults stay off.

When the operator is ready:

- [ ] Remove OmniRoute prefix `orcarouter/` and any OmniRoute full models like `oc/big-pickle` / `opencode-zen/mimo-v2.5-free`.
- [ ] Paste the Orca key into the OrcaRouter tab. Enable. Test connection. Add `orcarouter/auto` as a full model if they want the adaptive router.
- [ ] Paste the Zen key into the OpenCode Zen tab. Enable. Test connection. Cursor model id stays `opencode-zen/mimo-v2.5-free`.
- [ ] Enable OpenCode Free with no key. Test connection. Expect 429/503. Cursor model id stays `oc/big-pickle`.
- [ ] Restart `codex-lb.service` only after the operator confirms no other agent is using the shared instance.

---

## Final verification

- [ ] `openspec validate add-orcarouter-and-opencode-sidecar-routing --strict` passes.
- [ ] `SIDECAR_PROVIDER_ORDER` is exactly the locked tuple.
- [ ] Seeded prefixes are `orcarouter/` strip off, `opencode-zen/` strip on, `oc/` strip on. No `opencode/` seed.
- [ ] No `/v1/responses` branch for these providers.
- [ ] Request-log labels are `OrcaRouter` / `OpenCode Zen` / `OpenCode Free` with transport `HTTP`.
- [ ] `_OPAQUE_FREE_MODELS` contains `opencode-zen/big-pickle`.
- [ ] `synthetic-account-detail.tsx` does not treat Orca/Zen/Free as Claude.
- [ ] Every `BASE_SETTINGS` fixture compiles.
- [ ] `bun run build` from `frontend/` passes.
- [ ] Targeted pytest files pass.
- [ ] Git change list does not include `AGENTS.md`, `CLAUDE.md`, `CHANGELOG.md`, or `docs/`.

## If something goes wrong

- [ ] `bun run build` missing key: add the camelCase field to the fixture named in the error. Do not use `.optional()` to hide it.
- [ ] Uniqueness test fails to reject OmniRoute overlap: you forgot the new tuples in `_validate_unique_sidecar_routes` or `integrationValues()`.
- [ ] Chat for `orcarouter/auto` hits OmniRoute: `decision.provider` fallthrough still asserts OmniRoute. Add an explicit branch.
- [ ] Chat for `opencode-zen/mimo-v2.5-free` hits Free: Free accidentally owns `opencode-zen/` or `opencode/`. Remove that seed.
- [ ] Free test-connection skips the network: `_classify_static_status` still requires a key. Free must not.
- [ ] Alembic two heads: you parented the wrong revision. Add a merge revision or fix `down_revision`.
- [ ] PR too large for review: split implementation PRs as Orca first, then Zen+Free, keeping this OpenSpec change as the shared SSOT. Do not split the spec after implementation has started unless the operator asks.

## Requirement trace

- Chat routing / strip / effort / DeepSeek → Phases 3–6
- `/v1/models` owned_by + allowlist → Phase 6
- Settings tabs / conflicts / keyless Free test → Phases 2, 7, 10
- Effective model for API keys → Phase 6 routing tests
- Migration seeds → Phase 1
- Observability labels + cost + synthetics → Phase 8
