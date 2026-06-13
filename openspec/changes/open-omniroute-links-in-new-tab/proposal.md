# Proposal: Open OmniRoute links in a new tab

## Why

Today, every link in the codex-lb dashboard that points at the OmniRoute
sidecar (`/omni`) navigates the user **away from** the dashboard in the same
tab. OmniRoute is an external OpenAI-compatible control plane (it lives on
`127.0.0.1:20128` by default) that the operator may want to keep open in its
own tab while continuing to watch requests, change routing, or update model
IDs from the codex-lb dashboard. Same-tab navigation forces them to round-trip
back through the browser history every time they tweak a model list.

The dashboard is the primary surface for the operator; the OmniRoute UI is
secondary. Keep the operator in the dashboard by default.

## What changes

All anchors in the frontend that link to `/omni` MUST open in a new browser
tab and MUST set `rel="noopener noreferrer"` for safety.

Three anchor elements are affected (no new components, no new routes):

1. `frontend/src/components/layout/app-header.tsx` — the "OmniRoute" pill in
   the desktop nav (around line 73).
2. `frontend/src/components/layout/app-header.tsx` — the "OmniRoute" entry in
   the mobile `Sheet` menu (around line 140).
3. `frontend/src/features/settings/components/omniroute-sidecar-settings.tsx`
   — the "Open OmniRoute" outline `Button asChild` in the settings card
   (around line 114).

The visible `ExternalLink` icons stay. The label text stays. Only the
`target` and `rel` attributes change. No backend, no API, no schema, no
OpenSpec spec delta beyond this proposal.

## Out of scope

- Re-routing `/omni` through the codex-lb backend (OmniRoute stays an
  external sidecar).
- Changing other "Open …" buttons in the dashboard (none currently open
  external UIs besides OmniRoute).
- Adding a user preference to control the behavior. We hard-code
  "always new tab" for OmniRoute; if someone wants a same-tab override later
  it is a separate change.
- Keyboard / focus behavior beyond what `target="_blank"` already provides
  in the host browser. No custom `onClick` needed.

## Non-goals

- Do not introduce a new `Button` variant, a new `<NewTabLink>` wrapper, or
  a new helper component. The change is one attribute on each of the three
  anchors. If we ever need this in more places, a helper can be a follow-up.
