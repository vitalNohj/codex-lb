# OpenRouter Sidecar Settings UI — Execution Plan

**Goal (one sentence):** Give operators a focused Settings section where they can save an OpenRouter API key, configure model routing prefixes, and browse/search OpenRouter models (count, popular picks, full searchable list).

**Not in this plan:**

- OpenRouter request routing, proxy dispatch, or synthetic account backend (already shipped in `add-openrouter-sidecar-routing`)
- Quota polling, OAuth, auth plans, or Claude-style message sanitization
- Server-side model search API (client-side filter over `GET /api/openrouter-sidecar/models` is enough for v1)
- Adding OpenRouter model display names or pricing to the backend model summary (IDs only for now)
- Changing default empty model prefixes policy (operators still opt in explicitly)

**Before you start:**

- Read `frontend/src/features/settings/components/openrouter-sidecar-settings.tsx` — current UI exists but is operator-unfriendly (timeouts/base URL dominate; models truncated to 12 badges)
- Read `frontend/src/features/api-keys/components/model-multi-select.tsx` — reuse its search-in-dropdown pattern
- Read `frontend/src/features/settings/components/claude-sidecar-settings.tsx` — match its section layout (header, enable switch, save row, health strip, discovered models)
- Confirm backend endpoints work locally: `GET /api/openrouter-sidecar/status`, `POST /api/openrouter-sidecar/test`, `GET /api/openrouter-sidecar/models`
- Run from repo root: `cd frontend && npm test -- openrouter-sidecar-settings.test.tsx` (baseline should pass)

**Requirement traceability:**

| Operator need | Plan phases |
|---------------|-------------|
| Save API key | Phase 2 |
| Save model prefixes | Phase 2 |
| See how many models OpenRouter returns | Phase 3 |
| See popular models | Phase 3 |
| Search all models | Phase 4 |

---

## Phase 1: Restructure the settings section layout

**What this phase achieves:** The OpenRouter block reads like Claude sidecar — primary fields up front, advanced knobs tucked away.

- [ ] Step 1.1: Open `frontend/src/features/settings/components/openrouter-sidecar-settings.tsx`
- [ ] Step 1.2: Change the section header to match Claude sidecar structure — icon in rounded box, `h3` title, one-line subtitle, health badge on the right (reuse `formatSlug(currentStatus)`)
- [ ] Step 1.3: Add a short help callout (bordered muted box) explaining: get a key at https://openrouter.ai/settings/keys, configure provider prefixes like `deepseek/` to avoid overlapping native Codex `gpt-*` models
- [ ] Step 1.4: Move the enable switch into a divided row (label + description on left, switch on right) like Claude sidecar — keep instant save via `onSave({ openrouterSidecarEnabled })`
- [ ] Step 1.5: Create a `<details>` or collapsible "Advanced" block containing: Base URL, Connect timeout, Request timeout, Models cache TTL — default collapsed
- [ ] Step 1.6: Keep advanced field defaults unchanged (`https://openrouter.ai/api/v1`, 8 / 600 / 60 seconds)
- [ ] Step 1.7: Save the file and run `cd frontend && npm run build` — confirm no TypeScript errors

**Phase 1 done when:** Settings page shows enable switch + primary fields without advanced timeouts visible until expanded.

---

## Phase 2: Primary operator fields — API key and prefixes

**What this phase achieves:** Operators can paste a key, set prefixes, save once, and test connection.

- [ ] Step 2.1: In the primary (non-advanced) area, add two fields in a grid matching Claude sidecar:
  - API key — password input, placeholder `"Configured"` when `openrouterSidecarApiKeyConfigured`, helper text "Saved keys are encrypted and never shown again"
  - Model prefixes — comma-separated text input, helper text "Comma-separated provider prefixes, e.g. deepseek/, google/"
- [ ] Step 2.2: Add `id` and `htmlFor` on labels for accessibility (`openrouter-sidecar-api-key`, `openrouter-sidecar-prefixes`)
- [ ] Step 2.3: Keep `saveConfig()` sending:
  - `openrouterSidecarApiKey` only when the input is non-empty
  - `openrouterSidecarModelPrefixes` from parsed comma list (lowercase, deduped — existing `parsePrefixes`)
  - Advanced fields only when advanced section is visible / always include current advanced state on save (either is fine; pick one and stay consistent)
- [ ] Step 2.4: Add action row buttons (size `sm`, height `h-8`, text `text-xs` to match Claude):
  - "Save OpenRouter settings" — disabled when `busy` or base URL empty (advanced default satisfies this)
  - "Test connection" — calls `testMutation.mutateAsync()`
  - "Clear API key" — only when key configured; calls `save({ openrouterSidecarClearApiKey: true })`
- [ ] Step 2.5: After successful save with a new API key, clear the API key input field (already done via `setApiKey("")`)
- [ ] Step 2.6: Confirm `buildSettingsUpdateRequest` in `frontend/src/features/settings/payload.ts` already passes OpenRouter fields — no change expected unless a field was missing
- [ ] Step 2.7: Update `frontend/src/features/settings/components/openrouter-sidecar-settings.test.tsx`:
  - [ ] Step 2.7a: Assert save payload includes prefixes when user edits prefix input
  - [ ] Step 2.7b: Assert "Test connection" button exists and is clickable (mock mutation)
- [ ] Step 2.8: Run `cd frontend && npm test -- openrouter-sidecar-settings.test.tsx` — all tests pass

**Phase 2 done when:** Manual check — enter API key + `deepseek/, google/`, click Save, reload page, see `openrouterSidecarApiKeyConfigured: true` and prefixes persisted (via network tab or settings GET).

---

## Phase 3: Model count, health strip, and popular models

**What this phase achieves:** After key is saved and sidecar enabled, operators see connection health, total model count, and a curated list of well-known OpenRouter models.

- [ ] Step 3.1: Create `frontend/src/features/settings/components/openrouter-popular-models.ts` with a constant array of suggested model IDs (at least 8 entries), for example:
  - `deepseek/deepseek-chat`
  - `google/gemini-2.5-pro-preview`
  - `anthropic/claude-sonnet-4`
  - `meta-llama/llama-3.3-70b-instruct`
  - `qwen/qwen-2.5-72b-instruct`
  - `openai/gpt-4o-mini`
  - `mistralai/mistral-large`
  - `cohere/command-r-plus`
- [ ] Step 3.2: Export a helper `prefixFromModelId(id: string): string` that returns everything through the first `/` inclusive (e.g. `deepseek/deepseek-chat` → `deepseek/`)
- [ ] Step 3.3: Add a health summary strip (3-column grid, `text-xs`) below the action buttons:
  - Configured: yes/no from `sidecarApiKeyConfigured`
  - Models: `modelCount ?? "--"` from status query or settings fallback
  - Last check: formatted timestamp or "never"
- [ ] Step 3.4: Show `currentMessage` under the strip when present (muted text)
- [ ] Step 3.5: Add a "Popular models" subsection:
  - [ ] Step 3.5a: When `modelsQuery.data?.models` is non-empty, filter popular list to IDs that exist in the fetched catalog (case-sensitive ID match)
  - [ ] Step 3.5b: When models are not loaded yet (no key, disabled, or query idle), still show the static popular list with a muted note "Save API key and test connection to verify availability"
  - [ ] Step 3.5c: Render each popular model as a `Badge` with monospace ID
  - [ ] Step 3.5d: Add a small "Add prefix" button/link on each badge that appends `prefixFromModelId(id)` to the prefixes input if not already present (dedupe via `parsePrefixes`)
- [ ] Step 3.6: Wire `useOpenRouterSidecar()` models query to refetch when:
  - Sidecar is enabled AND API key is configured (`enabled: sidecarEnabled && sidecarApiKeyConfigured` in query `enabled` option)
  - Test connection mutation succeeds (already invalidates queries in hook — confirm in `use-settings.ts`)
- [ ] Step 3.7: Run dev server, save a real or test key, click Test connection — confirm model count updates and popular models section renders

**Phase 3 done when:** Health strip shows a numeric model count after test; popular models render; clicking "Add prefix" on `deepseek/deepseek-chat` adds `deepseek/` to the prefix field.

---

## Phase 4: Searchable model browser

**What this phase achieves:** Operators can search the full OpenRouter catalog returned by codex-lb without scrolling hundreds of badges.

- [ ] Step 4.1: Create `frontend/src/features/settings/components/openrouter-model-browser.tsx`
- [ ] Step 4.2: Props: `{ models: OpenRouterSidecarModelSummary[]; isLoading: boolean; onAddPrefix: (prefix: string) => void }`
- [ ] Step 4.3: Copy the search pattern from `model-multi-select.tsx`:
  - Local `search` state
  - `useMemo` filter: match `model.id` case-insensitively (no `name` field on OpenRouter summary yet)
  - Search input with placeholder "Search models..."
- [ ] Step 4.4: Render inside a bordered panel with max height (`max-h-64 overflow-y-auto`) — not a dropdown, a scrollable list so it works on the settings page
- [ ] Step 4.5: Each row shows:
  - Monospace model ID (primary)
  - Optional muted `ownedBy` when present
  - "Add prefix" action that calls `onAddPrefix(prefixFromModelId(model.id))`
- [ ] Step 4.6: When `filtered.length === 0`, show "No models match your search"
- [ ] Step 4.7: When `models.length === 0` and not loading, show "No models loaded — save API key and test connection"
- [ ] Step 4.8: When `models.length > 0`, show header: `Discovered models ({models.length})`
- [ ] Step 4.9: Import and render `OpenRouterModelBrowser` in `openrouter-sidecar-settings.tsx` below popular models; pass `onAddPrefix` that merges into prefixes state
- [ ] Step 4.10: Remove the old "Cached models" badge strip that only showed first 12 IDs (replaced by browser)
- [ ] Step 4.11: Add test `frontend/src/features/settings/components/openrouter-model-browser.test.tsx`:
  - [ ] Step 4.11a: Renders model count in header
  - [ ] Step 4.11b: Filters list when typing in search
  - [ ] Step 4.11c: Calls `onAddPrefix` when clicking add action
- [ ] Step 4.12: Run `cd frontend && npm test -- openrouter-model-browser.test.tsx openrouter-sidecar-settings.test.tsx`

**Phase 4 done when:** With 50+ models mocked in MSW, typing "deepseek" narrows the list; full count appears in header.

---

## Phase 5: MSW mocks and hook polish

**What this phase achieves:** Frontend tests and local dev work without a real OpenRouter key.

- [ ] Step 5.1: Open `frontend/src/test/mocks/handlers.ts`
- [ ] Step 5.2: Expand the `GET /api/openrouter-sidecar/models` handler to return at least 15 models including several from the popular list and varied prefixes (`deepseek/`, `google/`, `meta-llama/`)
- [ ] Step 5.3: Ensure `POST /api/openrouter-sidecar/test` returns `modelCount` matching the models array length
- [ ] Step 5.4: In `useOpenRouterSidecar()`, set `modelsQuery` `enabled: false` until settings indicate key is configured — pass a parameter or read from a sibling query; avoid 401 noise on first page load with no key
- [ ] Step 5.5: Add toast on test failure (already in hook) — confirm message is readable
- [ ] Step 5.6: Run full frontend settings tests: `cd frontend && npm test -- src/features/settings/components/`

**Phase 5 done when:** Fresh page load with no API key does not spam failed model requests; tests pass with expanded MSW data.

---

## Phase 6: OpenSpec note (optional, no new backend behavior)

**What this phase achieves:** Document the dashboard UX expectations without blocking on a full new change archive.

- [ ] Step 6.1: Add `openspec/changes/refine-openrouter-sidecar-settings-ui/context.md` with one paragraph: dashboard OpenRouter settings prioritize API key, prefixes, and model discovery; advanced timeouts remain available but collapsed
- [ ] Step 6.2: If you extend `openrouter-sidecar-management` spec, add one scenario: "Operator searches discovered OpenRouter models in Settings" — otherwise skip spec delta (UI-only refinement)
- [ ] Step 6.3: Run `openspec validate --strict` only if you added spec files

**Phase 6 done when:** Context doc exists OR you explicitly skipped because change is UI-only with no normative behavior change.

---

## Final verification

- [ ] Run `cd frontend && npm test -- openrouter-sidecar-settings openrouter-model-browser`
- [ ] Run `cd frontend && npm run build`
- [ ] Run `uv run pytest tests/integration/test_openrouter_sidecar_dashboard_api.py -q` — backend unchanged, should still pass
- [ ] Manual dashboard check (logged in):
  - [ ] Open `/settings#openrouter-sidecar`
  - [ ] Paste API key, set prefixes `deepseek/`, Save — toast success, key input clears, "Configured" placeholder appears
  - [ ] Enable sidecar switch
  - [ ] Click Test connection — health shows `healthy`, model count > 0
  - [ ] Popular models section visible
  - [ ] Search box filters discovered models
  - [ ] Click "Add prefix" on a model — prefix appears in input; Save persists it
  - [ ] Expand Advanced — base URL and timeouts still save correctly
  - [ ] Clear API key — configured flag false, models browser shows empty state

---

## If something goes wrong

- [ ] **Models query returns empty but test succeeds:** Check `useOpenRouterSidecar` query `enabled` guard — models fetch requires enabled + configured key
- [ ] **Model count stays `--`:** Status query may be stale; confirm test mutation invalidates `["settings", "openrouter-sidecar"]` keys
- [ ] **Save does not persist API key:** Inspect PATCH `/api/settings` payload for `openrouterSidecarApiKey`; confirm `buildSettingsUpdateRequest` merge logic
- [ ] **Prefix not routing requests:** Prefixes are routing config, not UI — verify `openrouterSidecarEnabled` is true and request model ID starts with saved prefix (backend concern; out of this plan)
- [ ] **Frontend test cannot find placeholder text:** Match exact placeholder strings from component after Phase 2 rewording

---

## File checklist (create or edit)

| File | Action |
|------|--------|
| `frontend/src/features/settings/components/openrouter-sidecar-settings.tsx` | Major edit — layout, primary fields, integrate browser |
| `frontend/src/features/settings/components/openrouter-model-browser.tsx` | Create — searchable list |
| `frontend/src/features/settings/components/openrouter-popular-models.ts` | Create — constants + prefix helper |
| `frontend/src/features/settings/components/openrouter-sidecar-settings.test.tsx` | Edit — cover new UX |
| `frontend/src/features/settings/components/openrouter-model-browser.test.tsx` | Create — search + add prefix |
| `frontend/src/features/settings/hooks/use-settings.ts` | Minor edit — models query enabled guard |
| `frontend/src/test/mocks/handlers.ts` | Edit — richer model fixtures |
| `openspec/changes/refine-openrouter-sidecar-settings-ui/context.md` | Create (optional) |

**No backend file changes expected** — reuse existing `/api/settings` and `/api/openrouter-sidecar/*` endpoints.
