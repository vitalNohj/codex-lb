# Open OmniRoute Links in a New Tab — Execution Plan

**Goal:** Make every link in the codex-lb frontend that points at the OmniRoute sidecar open in a new browser tab, so operators can keep the dashboard loaded while they manage OmniRoute.

**Not in this plan:**
- Re-routing `/omni` through the codex-lb backend (OmniRoute stays external).
- Refactoring the `AppHeader` or `OmniRouteSidecarSettings` components beyond the minimum needed.
- Adding a user preference / toggle for the behavior. Hard-code "always new tab" for OmniRoute only.
- Touching any backend module, schema, migration, or test outside the two frontend files and their tests.

**Before you start:**
- Working directory is `~/personal/codex-lb`.
- Frontend is built with Vite + React + TypeScript and tested with Vitest + Testing Library.
- The frontend `package.json` is invoked via `bun` (see `Makefile` / repo README). The OpenSpec CLI is installed in the dev environment and is invoked as `openspec …` from the repo root.
- The repo's merge gates (per `AGENTS.md`) require CI green, codex review clean, and an OpenSpec change folder for dashboard-visible changes. This plan satisfies that gate via the change folder at `openspec/changes/open-omniroute-links-in-new-tab/`.
- Do not start Step 2 until Step 1 is done; the new tests are regression tests for the edits made in Step 1.

---

## Phase 1: Add `target="_blank"` and `rel="noopener noreferrer"` to the three anchors

**What this phase achieves:** Every clickable surface in the dashboard that points at `/omni` opens OmniRoute in a new tab, with the security-correct `rel` value so the new tab cannot reach back into the codex-lb window via `window.opener`.

**Files to change:**
- `frontend/src/components/layout/app-header.tsx` (edit, two anchors)
- `frontend/src/features/settings/components/omniroute-sidecar-settings.tsx` (edit, one anchor)

- [ ] **Step 1.1:** Open `frontend/src/components/layout/app-header.tsx` in your editor and locate the desktop nav "OmniRoute" anchor.
  - It is the `<a href={OMNIROUTE_PATH} …>` element immediately after the `NAV_ITEMS.map(...)` `NavLink` list (around lines 73–79).
  - **Done when:** you can see the anchor in the file and confirm it currently has no `target` and no `rel`.

- [ ] **Step 1.2:** Edit that desktop anchor to add `target="_blank"` and `rel="noopener noreferrer"`.
  - Keep the existing `className`, the "OmniRoute" text, and the `<ExternalLink … />` icon child exactly as they are.
  - **Done when:** the anchor tag reads `<a href={OMNIROUTE_PATH} target="_blank" rel="noopener noreferrer" …>` (attribute order is not important, but both attributes must be present).

- [ ] **Step 1.3:** In the same file, locate the mobile menu "OmniRoute" anchor.
  - It is the `<a href={OMNIROUTE_PATH} …>` element inside the `SheetContent` `nav`, after the mobile `NavLink` list (around lines 140–147).
  - **Done when:** you can see the anchor and confirm it currently has no `target` and no `rel`.

- [ ] **Step 1.4:** Edit that mobile anchor to add `target="_blank"` and `rel="noopener noreferrer"`.
  - Keep the existing `className`, the `onClick={() => setMobileOpen(false)}` handler, the "OmniRoute" text, and the `<ExternalLink … />` icon child exactly as they are.
  - **Done when:** the anchor tag reads `<a href={OMNIROUTE_PATH} target="_blank" rel="noopener noreferrer" … onClick={…}>` and the `onClick` is still present so the mobile `Sheet` closes after the click.

- [ ] **Step 1.5:** Open `frontend/src/features/settings/components/omniroute-sidecar-settings.tsx` and locate the "Open OmniRoute" anchor.
  - It is the `<a href="/omni">` child of the `<Button asChild type="button" size="sm" variant="outline" …>` (around lines 114–119).
  - **Done when:** you can see the anchor and confirm it currently has no `target` and no `rel`.

- [ ] **Step 1.6:** Edit that anchor to add `target="_blank"` and `rel="noopener noreferrer"`.
  - Keep the `<ExternalLink … />` icon and the "Open OmniRoute" label exactly as they are. Do not change the surrounding `<Button asChild …>` props.
  - **Done when:** the anchor reads `<a href="/omni" target="_blank" rel="noopener noreferrer">` (order of attributes is not important, but both attributes must be present).

- [ ] **Step 1.7:** Run a quick `Grep` for `href="/omni"` and `href={OMNIROUTE_PATH}` from the repo root to confirm only the three expected anchors are present and all three now have `target="_blank"` and `rel="noopener noreferrer"`.
  - Command: `rg -n 'href=("|{)/omni' frontend/src`
  - **Done when:** the grep prints exactly three lines (one per anchor) and a follow-up `rg -n 'rel="noopener noreferrer"' frontend/src` prints at least three lines (the same three anchors).

**Phase 1 done when:** the three anchors open in a new tab when clicked and carry `rel="noopener noreferrer"` for `window.opener` hardening. No other markup, class names, or behavior changed.

---

## Phase 2: Add regression tests for the new attributes

**What this phase achieves:** A future refactor that accidentally drops the new-tab behavior (e.g. someone "cleans up" the attributes or swaps the anchor for a router `Link`) fails CI before it ships.

**Files to change:**
- `frontend/src/features/settings/components/omniroute-sidecar-settings.test.tsx` (edit, add one new `it` block)
- `frontend/src/components/layout/app-header.test.tsx` (create OR edit, add a new `it` block)

- [ ] **Step 2.1:** Open `frontend/src/features/settings/components/omniroute-sidecar-settings.test.tsx`.
  - **Done when:** the file is open and you can see the existing `describe("OmniRouteSidecarSettings", …)` block with the three existing tests.

- [ ] **Step 2.2:** Add a new `it("opens the OmniRoute link in a new tab", …)` block inside the existing `describe`. Place it as the **last** test in the file so existing test order is preserved.
  - Inside the test, call `renderWithQueryClient(<OmniRouteSidecarSettings settings={BASE_SETTINGS} busy={false} onSave={onSave} />)` exactly like the other tests do (`onSave` is `vi.fn().mockResolvedValue(undefined)`).
  - **Done when:** the new test compiles and is visible in the file.

- [ ] **Step 2.3:** Inside that new test, query the anchor and assert both attributes.
  - Query: `const link = screen.getByRole("link", { name: /open omniroute/i });`
  - Assertion 1: `expect(link).toHaveAttribute("target", "_blank");`
  - Assertion 2: `expect(link).toHaveAttribute("rel", "noopener noreferrer");`
  - **Done when:** the test body looks like:
    ```ts
    const link = screen.getByRole("link", { name: /open omniroute/i });
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
    ```

- [ ] **Step 2.4:** Run only this test file to confirm the new test passes alongside the three existing ones.
  - Command: `cd frontend && bunx vitest run src/features/settings/components/omniroute-sidecar-settings.test.tsx`
  - **Done when:** Vitest reports 4 passing tests, 0 failing. The new test appears by its title in the output.

- [ ] **Step 2.5:** Check whether `frontend/src/components/layout/app-header.test.tsx` already exists.
  - Command: `ls frontend/src/components/layout/app-header.test.tsx`
  - **Done when:** you know which of the two sub-steps below applies.

- [ ] **Step 2.6 (only if the file does not exist):** Create `frontend/src/components/layout/app-header.test.tsx` with the minimum scaffolding needed to render `<AppHeader />` inside a router and assert on the desktop nav link.
  - At the top, import: `describe, expect, it, vi` from `"vitest"`; `render, screen` from `"@testing-library/react"`; `MemoryRouter` from `"react-router-dom"`; `AppHeader` from `"@/components/layout/app-header"`.
  - Inside a `describe("AppHeader", …)` block, add one `it("opens the OmniRoute link in a new tab", …)` test that calls `render(<MemoryRouter><AppHeader onLogout={vi.fn()} /></MemoryRouter>)`.
  - Query the desktop nav link: `screen.getByRole("link", { name: /omniroute/i })`.
  - Assert: `expect(link).toHaveAttribute("target", "_blank");` and `expect(link).toHaveAttribute("rel", "noopener noreferrer");`.
  - **Done when:** the file exists, the test compiles, and the desktop nav anchor is the one returned by `getByRole`. If the query is ambiguous in your test environment, scope it with `screen.getAllByRole("link", { name: /omniroute/i })[0]` and assert the first visible nav link carries the attributes.

- [ ] **Step 2.7 (only if the file already exists):** Add the same `it("opens the OmniRoute link in a new tab", …)` block described in Step 2.6 to the existing `describe` for `AppHeader`.
  - **Done when:** the new test exists in the existing file and the rest of the file is untouched.

- [ ] **Step 2.8:** Run the new app-header test.
  - Command: `cd frontend && bunx vitest run src/components/layout/app-header.test.tsx`
  - **Done when:** Vitest reports the new test passing, 0 failing.

- [ ] **Step 2.9:** Run the full frontend test suite to confirm nothing else regressed.
  - Command: `cd frontend && bunx vitest run`
  - **Done when:** the summary line shows 0 failing tests. (Total test count will go up by 1 or 2 — that is expected.)

**Phase 2 done when:** both test files are green, the new tests fail if you temporarily remove either `target` or `rel` (sanity check: do this in a scratch branch, see the failure, then revert), and no existing test was modified or removed.

---

## Phase 3: Build and manual smoke test

**What this phase achieves:** Confirms the change builds cleanly and behaves correctly in a real browser at all three affected surfaces (desktop nav, mobile menu, settings card).

- [ ] **Step 3.1:** From `frontend/`, run the production build.
  - Command: `cd frontend && bun run build`
  - **Done when:** the build finishes with `✓ built in …` and no TypeScript or Vite errors. The `index-*.js` chunk hash in the build output is different from the previous build (proof the file was rebuilt).

- [ ] **Step 3.2:** Restart the codex-lb service so the rebuilt static assets are served.
  - Command: `cd .. && systemctl --user restart codex-lb.service`
  - **Done when:** `systemctl --user status codex-lb.service` shows `active (running)`. If you use a different restart command in this environment, use that and confirm the service is active.

- [ ] **Step 3.3:** Open the dashboard in a desktop browser tab. Click the "OmniRoute" pill in the top nav.
  - **Done when:** OmniRoute opens in a new tab, the original tab is still on the dashboard, and the original tab does not navigate. The `ExternalLink` icon next to the label is still visible.

- [ ] **Step 3.4:** Open the mobile menu (resize the browser to a narrow width, or use devtools device emulation). Tap "OmniRoute".
  - **Done when:** OmniRoute opens in a new tab **and** the mobile `Sheet` closes. The original tab is still on the dashboard.

- [ ] **Step 3.5:** Navigate to the `Settings` page and scroll to the OmniRoute Sidecar card. Click the "Open OmniRoute" outline button.
  - **Done when:** OmniRoute opens in a new tab and the settings page is still loaded in the original tab.

- [ ] **Step 3.6:** In each new tab, confirm the page loads the OmniRoute UI at the configured `/omni` route (or at the deployment's OmniRoute proxy/redirect target).
  - **Done when:** the three new tabs all render OmniRoute and the original dashboard tab remains on its previous codex-lb route.

**Phase 3 done when:** all three surfaces open OmniRoute in a new tab and the dashboard tab is never navigated away from.

---

## Phase 4: OpenSpec validation, commit, and archive

**What this phase achieves:** The repo's merge gates are satisfied: the OpenSpec change is valid, the change is committed referencing the OpenSpec folder, and once merged the change is archived so it leaves the active changes list.

- [ ] **Step 4.1:** From the repo root, validate the change folder.
  - Command: `openspec validate --change open-omniroute-links-in-new-tab`
  - **Done when:** the command exits 0 and prints a success line. If it prints errors, fix the change folder (most often: missing section headings in `proposal.md` / `tasks.md`) and re-run until clean.

- [ ] **Step 4.2:** Stage the edited frontend files, the test file(s) from Phase 2, and the OpenSpec change folder.
  - Files (relative to repo root):
    - `frontend/src/components/layout/app-header.tsx`
    - `frontend/src/features/settings/components/omniroute-sidecar-settings.tsx`
    - `frontend/src/features/settings/components/omniroute-sidecar-settings.test.tsx`
    - `frontend/src/components/layout/app-header.test.tsx` (only if you created it in Step 2.6)
    - `openspec/changes/open-omniroute-links-in-new-tab/`
  - **Done when:** `git status` shows the frontend files and the OpenSpec change folder as staged, and nothing unrelated is staged.

- [ ] **Step 4.3:** Commit the frontend changes.
  - Suggested message subject: `feat(ui): open OmniRoute links in a new tab`
  - Suggested message body: a one-line summary plus `OpenSpec: openspec/changes/open-omniroute-links-in-new-tab` and a `Requirements:` bullet pointing at the `proposal.md`.
  - Command: `git commit -m "$(cat <<'EOF'\nfeat(ui): open OmniRoute links in a new tab\n\nRequirement: openspec/changes/open-omniroute-links-in-new-tab/proposal.md\nOpenSpec: openspec/changes/open-omniroute-links-in-new-tab\nEOF\n)"`
  - **Done when:** `git log -1` shows the new commit and `git status` is clean for those files.

- [ ] **Step 4.4:** Open a PR against `main` and let CI run. Do **not** self-merge.
  - **Done when:** the PR is open, the OpenSpec change folder path is referenced in the PR body, and the merge gates from `.github/CONTRIBUTING.md` are tracked (CI green, codex review clean, `mergeable=CLEAN`).

- [ ] **Step 4.5:** After the PR is merged, archive the OpenSpec change.
  - Command: `openspec archive open-omniroute-links-in-new-tab`
  - **Done when:** `ls openspec/changes/open-omniroute-links-in-new-tab` reports the folder no longer exists, and `ls openspec/changes/archive/ | tail -5` shows a new dated folder whose name ends in `open-omniroute-links-in-new-tab`.

**Phase 4 done when:** the change is merged, archived, and the active `openspec/changes/` list no longer contains this folder.

---

## Final verification

- [ ] V1. Confirm `rg -n 'href=("|{)/omni' frontend/src` shows exactly three lines and all three anchors have `target="_blank"` and `rel="noopener noreferrer"`.
- [ ] V2. Confirm `cd frontend && bunx vitest run` reports 0 failing tests.
- [ ] V3. Confirm `openspec validate --specs` still reports no issues (it should, since this change did not add a spec delta — the requirement lives in the change `proposal.md`).
- [ ] V4. Confirm the PR is mergeable per the GitHub merge-gate checklist (CI green, codex review clean, `mergeable=CLEAN`).
- [ ] V5. Confirm the manual smoke checks in Phase 3 all passed.

---

## If something goes wrong

- [ ] W1. **Vitest says `getByRole` cannot find the link.** The label might not match — print the rendered HTML with `screen.debug()` and adjust the regex. The desktop nav label is exactly `"OmniRoute"`, and the settings button label is `"Open OmniRoute"` plus the `ExternalLink` icon, which Testing Library collapses into a single accessible name.
- [ ] W2. **Build fails with a TypeScript error on the anchor.** Make sure `target` and `rel` are on the `<a>` element, not on the surrounding `<Button asChild>` (Radix `asChild` forwards attributes to its child, but adding them on the child is the documented pattern and avoids TS overload surprises).
- [ ] W3. **The mobile `Sheet` does not close after the new-tab click.** You accidentally moved or removed the `onClick={() => setMobileOpen(false)}` handler in Step 1.4. Put it back. The `target="_blank"` navigation does not block the `onClick` from firing, so both should still work.
- [ ] W4. **A codex review thread flags a missing security concern.** Double-check `rel="noopener noreferrer"` is present (not just `rel="noopener"`). The `noreferrer` part is what prevents the new tab from learning the codex-lb URL via `document.referrer`.
- [ ] W5. **The OpenSpec `validate` step complains about missing sections.** The repo's spec-driven schema requires `proposal.md` and `tasks.md`. Both are created in this plan; if either is renamed or its section headings are altered, validation will fail.
- [ ] W6. **CI fails on a lint rule.** Run `cd frontend && bunx eslint src` to see the local lint output. The change is attribute-only, so any lint failure is almost certainly in a neighboring line that was already broken — do not "fix" unrelated lint, just narrow the diff to the three anchors and the new tests.
