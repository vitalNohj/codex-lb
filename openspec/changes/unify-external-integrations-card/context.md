# Context: Unify external integrations card

## Decision

The three external integration settings cards (CLIProxyAPI, OpenRouter,
OmniRoute) are consolidated into a single bordered card titled "External
Integrations" with a `Tabs` switcher — one tab per integration. A planned
fourth integration (Ollama) will be added later as one more tab.

This is a dashboard-visible UI refinement with **no normative behavior change**
(no API, schema, routing, or save-payload changes), so it follows the
established UI-only precedent (e.g. `refine-openrouter-sidecar-settings-ui`) and
declares **no spec deltas**.

## Why this shape

- **Compactness**: stacking three (soon four) identical full-width cards makes
  the Settings page long and hard to scan. Tabs collapse them to one card.
- **Isolation preserved**: each integration keeps its own provider, state,
  hooks, and conflict detection. The unified card only adds an outer card +
  tab switcher. This keeps each integration independently testable and means
  the consolidation cannot change save/routing behavior.
- **Extensibility**: the tab list in `SidecarIntegrationsCard` is a data-driven
  array of `{ value, label, enabled, render }`. Adding Ollama is one new
  settings component plus one array entry — no structural change.

## Key constraints / failure modes

- **No nested cards**: `SidecarIntegrationCard.Frame` gained a `bare` prop. The
  unified card renders each integration with `bare`, dropping the inner
  border/padding so it does not look like a card-in-a-card. `bare` defaults to
  `false`, so standalone usage and existing tests are unaffected.
- **Anchor links preserved**: even when `bare`, the Frame keeps its section
  `id` (`claude-sidecar`, `openrouter-sidecar`, `omniroute-sidecar`) so deep
  links continue to resolve. The outer card also exposes
  `id="external-integrations"`.
- **Default tab**: computed once from `settings` on mount (lazy state init) as
  the first enabled integration, falling back to the first tab. Not persisted.
- **Enabled indicator**: tab labels show an `aria-hidden` dot when enabled and
  add an `(enabled)` suffix to the trigger `aria-label` for screen readers.

## Example

Operator opens `/settings` with only OpenRouter enabled. The "External
Integrations" card opens on the OpenRouter tab (its label shows a green dot,
the CLIProxyAPI/OmniRoute tabs do not). Switching to the CLIProxyAPI tab shows
the CLIProxyAPI configuration exactly as before, with the same fields, save
behavior, and conflict messages.

## Affected files

- `frontend/src/features/settings/components/sidecar-integrations.tsx` (new) —
  the unified tabbed card.
- `frontend/src/features/settings/components/sidecar-integration-card.tsx` —
  `Frame` gains optional `bare` prop.
- `frontend/src/features/settings/components/{claude,openrouter,omniroute}-sidecar-settings.tsx`
  — accept and forward optional `bare` prop.
- `frontend/src/features/settings/components/settings-page.tsx` — render the
  single unified card instead of three siblings.
- `frontend/src/features/settings/components/sidecar-integrations-card.test.tsx`
  (new) — tab rendering, default-enabled tab, fallback, tab switching.
