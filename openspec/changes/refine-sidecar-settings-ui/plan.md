# Refine OpenRouter and OmniRoute Settings UI — Execution Plan

**Goal:** Apply the same restyling done to `ClaudeSidecarSettings` to `OpenRouterSidecarSettings` and `OmniRouteSidecarSettings` — remove "sidecar" labels, remove header status badges and bottom health strips, move the enable toggle above the explanation callout, collapse fields into compact rows, and rename "Save ... settings" to "Save".

**Not in this plan:**
- Backend changes (schema, API, routing, model endpoints)
- `ClaudeSidecarSettings` changes (already done)
- `OpenRouterModelBrowser`, `OmniRouteModelBrowser`, or `openrouter-popular-models` helper (no user-visible "sidecar" text)
- Any `aria-label` on icons or decorative elements beyond what's listed

**Before you start:**
- Read the final `ClaudeSidecarSettings.tsx` file to see the reference layout pattern (toggle before callout, two configuration rows, save/test/clear buttons in one row, no health strip, no header badge, "Save" not "Save sidecar")
- Run `bun run build` from `/frontend` to confirm tsc + vite pass clean before changing anything
- Open both `openrouter-sidecar-settings.tsx` and `omniroute-sidecar-settings.tsx` in your editor side by side

## Phase 1: OpenRouter Sidecar

**What this phase achieves:** The OpenRouter settings card gets the same compact layout as the Claude card. 2 files change: the component and its test.

### Step 1.1 — Update user-visible label strings

- [ ] Open `frontend/src/features/settings/components/openrouter-sidecar-settings.tsx`
- [ ] Line 103: change heading `<h3>OpenRouter Integration</h3>` — keep this, no "sidecar"
- [ ] Line 107: delete the `<Badge>` line with `{formatSlug(currentStatus)}`
- [ ] Line 107: after removing the badge line, simplify the header wrapper so the icon/title row is just `<div className="flex items-center gap-2.5">...</div>` with no empty right-aligned content.
- [ ] Line 119: change "Enable OpenRouter sidecar" to "Enable OpenRouter Integration" (the `<p>` label)
- [ ] Line 120-122: change subtitle text
- [ ] Line 125: change `aria-label="Enable OpenRouter sidecar"` to `aria-label="Enable OpenRouter Integration"`
- [ ] Line 220: change button text "Save OpenRouter settings" to "Save"
- [ ] Delete the `formatSlug` import from line 16 if it becomes unused (check: it was only used on the badge)
- [ ] Delete the `formatDateTimeInline` import from line 16 if it becomes unused (check: it was only used in the health strip)

### Step 1.2 — Remove bottom health strip and status message

- [ ] Lines 248-259: delete the entire `<div className="grid gap-3 rounded-lg border ... sm:grid-cols-3">` block (Configured / Models / Last check)
- [ ] Line 260: delete `{currentMessage ? <p ...>{currentMessage}</p> : null}`
- [ ] In the variable declarations section (~lines 63-66), remove `currentStatus`, `currentMessage`, `lastChecked`, `modelCount` since they are now unused

### Step 1.3 — Move enable toggle above the explanation callout

- [ ] Cut the enable toggle section (lines 116-130, the entire `<div className="flex items-center justify-between gap-4 p-3">` containing the Switch) from inside the `divide-y rounded-lg border` wrapper
- [ ] Paste it between the header section and the explanation `<div className="rounded-lg border bg-muted/20 p-3 ...">` callout
- [ ] The toggle now wraps itself in `<div className="flex items-center justify-between gap-4 rounded-lg border p-3">` (same as Claude — give it its own border since it sits outside the config border wrapper now)

### Step 1.4 — Restructure config fields into compact rows

- [ ] Remove the `divide-y` class from the config border wrapper `<div>` (it now only has the config block, no toggle row inside it)
- [ ] In the config `<div className="space-y-3 p-3">`, rearrange fields into:
  - **Base URL** (full width, unchanged — lines 168-178)
  - **Row 1** (2 equal columns): **API key** | **Model prefixes** (current lines 134-162, keep their subtext)
  - **Row 2** (3 equal columns): **Connect timeout (s)** | **Request timeout (s)** | **Model cache TTL (s)** (pull these out of the `<details>` Advanced block, format same as Claude: `type="number"` inputs with `h-8 text-xs`)
- [ ] Delete the entire `<details>` Advanced block (lines 165-210) since all its fields are now in the main layout
- [ ] Keep the buttons row: **Save** | **Test connection** | **Clear API key**
  - Change the Save button size to `className="h-8 text-xs"` (match Claude)
  - The Clear API key button should be unconditional (not conditionally rendered) like Claude's — change it from `{sidecarApiKeyConfigured ? <Button>...` to always-rendered `<Button>` with `disabled={busy || !sidecarApiKeyConfigured}`

### Step 1.5 — Verify available models are shown

- [ ] The existing "Popular models" + `<OpenRouterModelBrowser>` sections (lines 262-289) already show the models from `modelsQuery`. No new "Available models" block needed. But verify they render correctly with the new layout — the `modelsQuery` hook and `modelRows` variable should still be in the component. If you deleted `modelCount` in step 1.2, make sure you kept `modelRows` (line 67).

### Step 1.6 — Update OpenRouter test file

- [ ] Open `frontend/src/features/settings/components/openrouter-sidecar-settings.test.tsx`
- [ ] Line 67: change `name: "Enable OpenRouter sidecar"` to `name: "Enable OpenRouter Integration"`
- [ ] Line 71: change `name: "Save OpenRouter settings"` to `name: /^Save$/` (regex to avoid matching "Save quota estimates" if one existed)
- [ ] Line 93: same replacement
- [ ] Run full test suite once: `npx vitest run src/features/settings/components/openrouter-sidecar-settings.test.tsx` — all tests must pass

### Step 1.7 — Clean unused exports

- [ ] Run `bun run build` from `frontend/` and confirm `tsc -b && vite build` exits 0
- [ ] If tsc errors on unused imports (`formatSlug`, `formatDateTimeInline`, etc.), remove them from the import statement

## Phase 2: OmniRoute Sidecar

**What this phase achieves:** The OmniRoute settings card gets the same treatment. 2 files change.

### Step 2.1 — Update user-visible label strings

- [ ] Open `frontend/src/features/settings/components/omniroute-sidecar-settings.tsx`
- [ ] Line 120: delete the `<Badge>` line with `{formatSlug(currentStatus)}`
- [ ] The header area now has the icon + heading on the left and the "Open OmniRoute" link button on the right. Keep the outer `justify-between` wrapper because the link should remain right-aligned.
- [ ] Line 132: change "Enable OmniRoute sidecar" to "Enable OmniRoute Integration" (the `<p>` label)
- [ ] Line 138: change `aria-label="Enable OmniRoute sidecar"` to `aria-label="Enable OmniRoute Integration"`
- [ ] Line 270: change button text "Save OmniRoute settings" to "Save"
- [ ] Delete `formatSlug` import if unused; keep `formatDateTimeInline` if used only in the health strip (check: if the health strip is removed, delete the import too)

### Step 2.2 — Remove bottom health strip and status message

- [ ] Lines 298-309: delete the entire `<div className="grid gap-3 rounded-lg border ... sm:grid-cols-3">` block
- [ ] Line 310: delete `{currentMessage ? <p ...>{currentMessage}</p> : null}`
- [ ] In variable declarations (~lines 60-63), remove `currentStatus`, `currentMessage`, `lastChecked`, `modelCount`

### Step 2.3 — Move enable toggle above the explanation callout

- [ ] Cut the enable toggle section (lines 129-143, the `<div className="flex items-center justify-between gap-4 p-3">` containing the Switch) from inside the `divide-y rounded-lg border` wrapper
- [ ] Paste it between the header section and the explanation `<div className="rounded-lg border bg-muted/20 p-3 ...">` callout
- [ ] Wrap it in `<div className="flex items-center justify-between gap-4 rounded-lg border p-3">` like Claude

### Step 2.4 — Restructure config fields into compact rows

- [ ] Remove the `divide-y` class from the config wrapper
- [ ] In the config block, rearrange into:
  - **Base URL** (full width)
  - **Row 1** (2 columns): **API key** | **Add model ID manually** (the inline input + Add button combo, keep as-is)
  - Selected models chips (unchanged)
  - **Row 2** (3 equal columns): **Connect timeout (s)** | **Request timeout (s)** | **Model cache TTL (s)** (pull out of `<details>` block)
- [ ] Delete the entire `<details>` Advanced block (lines 215-260) since all fields are now in the main layout
- [ ] Keep the buttons row: **Save** | **Test connection** | **Clear API key**
  - Same changes as OpenRouter: always-rendered Clear API key, `h-8 text-xs` on Save

### Step 2.5 — Verify models section

- [ ] The `<OmniRouteModelBrowser>` (lines 312-318) stays as-is. It shows discoverable models with add/remove actions.
- [ ] Make sure `modelsQuery` and `modelRows` are still declared (not removed with `modelCount` in step 2.2)

### Step 2.6 — Update OmniRoute test file

- [ ] Open `frontend/src/features/settings/components/omniroute-sidecar-settings.test.tsx`
- [ ] Line 69: change `name: "Enable OmniRoute sidecar"` to `name: "Enable OmniRoute Integration"`
- [ ] Line 73: change `name: "Save OmniRoute settings"` to `name: /^Save$/`
- [ ] Line 95: same replacement
- [ ] Keep a `"tests the connection"` test, but change it to assert that the `Test connection` button is enabled and clickable. Do not assert on `OmniRoute sidecar reachable` because that message no longer renders.
- [ ] Keep the last test `it("opens the OmniRoute link in a new tab"...` unchanged except for any line-number drift.
- [ ] Run tests: `npx vitest run src/features/settings/components/omniroute-sidecar-settings.test.tsx` — all must pass

## Phase 3: Final verification

- [ ] Run `cd frontend && npx vitest run` — all tests pass (not just the changed ones)
- [ ] Run `cd frontend && bun run build` — tsc + vite exit 0
- [ ] Open a browser to the Settings page and visually confirm all three integration sections are consistent:
  - No "sidecar" in any visible label
  - Enable toggle sits above the explanation callout
  - Header has no status badge
  - No "Configured / Models / Last check" strip at the bottom
  - No "X sidecar reachable" status message text
  - Save button says "Save" on all three
  - Models are displayed (OpenRouter popular models + browser, OmniRoute browser, Claude available models)

## If something goes wrong

- [ ] If a test asserts on "Enable ... sidecar" or "Save ... settings" and I missed one, grep for `getByRole.*sidecar` or `getByText.*settings` in the test files
- [ ] If tsc complains about unused `formatSlug` / `formatDateTimeInline` that I already removed, check the import line — there may be other imports sharing that line
- [ ] If the layout looks broken (e.g. fields overlapping), check that the `grid-cols-N` classes match the number of children in each grid row
- [ ] If the `tests the connection` test error is something else unexpected, read the error carefully — it might assert a toast or mutation that still works but the assertion text changed
