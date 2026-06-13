# Tasks: open-omniroute-links-in-new-tab

## 1. Frontend: add `target` and `rel` to the three anchors

- [x] 1.1. Open `frontend/src/components/layout/app-header.tsx`.
- [x] 1.2. Locate the desktop nav `<a href={OMNIROUTE_PATH} …>` element
      (the pill with the `ExternalLink` icon, just after the
      `NAV_ITEMS.map(...)` `NavLink` list).
- [x] 1.3. Add `target="_blank"` and `rel="noopener noreferrer"` to that
      anchor. Keep all other props and children untouched.
- [x] 1.4. Locate the mobile menu `<a href={OMNIROUTE_PATH} …>` element
      (inside the `SheetContent` `nav`, after the mobile `NavLink` list).
- [x] 1.5. Add `target="_blank"` and `rel="noopener noreferrer"` to that
      anchor. Keep the existing `onClick={() => setMobileOpen(false)}` and
      the `ExternalLink` icon child as-is.
- [x] 1.6. Open `frontend/src/features/settings/components/omniroute-sidecar-settings.tsx`.
- [x] 1.7. Locate the `<Button asChild>` whose child is `<a href="/omni">`
      (the "Open OmniRoute" outline button in the card header).
- [x] 1.8. Add `target="_blank"` and `rel="noopener noreferrer"` to that
      anchor. Keep the `<ExternalLink>` icon and the "Open OmniRoute" label
      untouched.

**Why:** these three anchors are the only places the frontend links to the
external OmniRoute sidecar. A new tab keeps the dashboard reachable.

## 2. Frontend: add unit-test coverage for the new attributes

- [x] 2.1. Open `frontend/src/features/settings/components/omniroute-sidecar-settings.test.tsx`.
- [x] 2.2. Add a new `it(...)` block titled
      `"opens the OmniRoute link in a new tab"`.
- [x] 2.3. Inside that test, render `<OmniRouteSidecarSettings … />` with
      the existing `BASE_SETTINGS` and a `vi.fn().mockResolvedValue(undefined)`
      for `onSave`.
- [x] 2.4. Query the anchor with
      `screen.getByRole("link", { name: /open omniroute/i })`.
- [x] 2.5. Assert that anchor has
      `expect(link).toHaveAttribute("target", "_blank")`.
- [x] 2.6. Assert that anchor has
      `expect(link).toHaveAttribute("rel", "noopener noreferrer")`.
- [x] 2.7. Run `cd frontend && bunx vitest run src/features/settings/components/omniroute-sidecar-settings.test.tsx`
      and confirm the new test passes alongside the existing three tests.
- [x] 2.8. Add an `AppHeader` test in `frontend/src/components/layout/app-header.test.tsx`
      that renders the header in a router and asserts the desktop nav link to
      OmniRoute has `target="_blank"` and `rel="noopener noreferrer"`.
  - [x] 2.8a. If `app-header.test.tsx` does not exist, create it and render
        `<AppHeader onLogout={vi.fn()} />` inside a router before asserting
        the desktop nav link to OmniRoute carries the two attributes.
  - [x] 2.8b. Re-run `bunx vitest run` for the new test file and confirm
        it passes.

**Why:** the existing settings test file already covers save/clear flows
in this component; the new tab behavior is the externally visible contract
of the change, so it gets regression coverage at the product surface.

## 3. Manual verification

- [x] 3.1. From `frontend/`, run `bun run build` and confirm it succeeds.
- [ ] 3.2. Start the dev server (or load the production build) and open the
      dashboard.
- [ ] 3.3. In the desktop header, click the "OmniRoute" pill and confirm
      the OmniRoute UI opens in a new tab while the dashboard tab is
      unchanged. Close the new tab; the dashboard tab must still be on
      whatever page it was on.
- [ ] 3.4. Resize to a mobile-width viewport (or open devtools device
      emulation). Open the hamburger menu and tap "OmniRoute". Confirm
      the same new-tab behavior and confirm the mobile `Sheet` closes.
- [ ] 3.5. Navigate to `Settings`, scroll to the OmniRoute Sidecar card,
      click "Open OmniRoute", and confirm it opens in a new tab while the
      settings page stays loaded.
- [ ] 3.6. In each new tab, confirm the page loads the OmniRoute UI at the
      configured `/omni` route (or at the deployment's OmniRoute proxy/redirect
      target) and that the original dashboard tab remains unchanged.

## 4. OpenSpec validation and archive

- [x] 4.1. From repo root, run `openspec validate open-omniroute-links-in-new-tab --type change`
      and confirm it reports no issues.
- [ ] 4.2. Stage the modified frontend files, test file(s), and OpenSpec
      change folder.
- [ ] 4.3. Commit with message:
      `feat(ui): open OmniRoute links in a new tab` (subject line) and
      reference `OpenSpec: openspec/changes/open-omniroute-links-in-new-tab`
      in the body.
- [ ] 4.4. After CI is green and the PR is merged, run
      `openspec archive open-omniroute-links-in-new-tab` so the change
      moves to `openspec/changes/archive/YYYY-MM-DD-open-omniroute-links-in-new-tab/`.
