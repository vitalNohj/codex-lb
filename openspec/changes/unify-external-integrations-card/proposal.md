# Proposal: Unify external integration settings into one tabbed card

## Why

The dashboard Settings page renders three separate, visually identical cards
back-to-back — CLIProxyAPI Integration, OpenRouter Integration, and OmniRoute
Integration. Each is a full-width bordered `<section>` with the same layout
(header, enable toggle, callout, fields). Stacking them vertically makes the
Settings page long and makes it hard to compare integrations at a glance. A
fourth integration (Ollama) is planned, which would make the stack even longer.

Combining them into a single "External Integrations" card with a tab per
integration keeps the page compact, presents the integrations as a coherent
group, and gives a single, obvious place to add the upcoming Ollama tab.

## What changes

- Add a single `SidecarIntegrationsCard` component that renders one bordered
  card titled "External Integrations" with a `Tabs` switcher (one tab per
  integration) and renders the existing integration settings components inside
  each tab.
- Each tab label MUST show a subtle enabled indicator (a small dot) when that
  integration is currently enabled, and expose an accessible `(enabled)` suffix
  in its `aria-label`.
- The card MUST default to the first **enabled** integration's tab on load,
  falling back to the first tab when none are enabled. Tab selection is not
  persisted across reloads.
- The shared `SidecarIntegrationCard.Frame` gains an optional `bare` prop. When
  `bare`, it renders without its own border/padding (so the integrations do not
  appear as nested cards inside the unified card) while preserving the section
  anchor `id`. Default behavior is unchanged.
- The three integration components (`ClaudeSidecarSettings`,
  `OpenRouterSidecarSettings`, `OmniRouteSidecarSettings`) accept an optional
  `bare` prop they forward to `Frame`. Their public behavior, save payloads,
  conflict detection, hooks, labels, and standalone rendering are unchanged.
- `settings-page.tsx` replaces the three sibling cards with the single
  `SidecarIntegrationsCard`.

This is a UI reorganization only. No backend, API, schema, routing, or save
behavior changes. Each integration keeps its own provider and state; the unified
card only wraps them in a shared outer card plus a tab switcher.

## Out of scope

- The Ollama integration itself. The tab list is data-driven so adding Ollama
  later is one settings component plus one array entry; this change does not add
  it.
- Any change to integration save payloads, conflict detection, model discovery,
  quota polling, or routing.
- Persisting the selected tab across reloads.

## Non-goals

- Merging the three integration providers/state into one. Each integration
  remains an independent, separately testable component.
