# Tasks: Unify external integrations card

- [x] Add optional `bare` prop to `SidecarIntegrationCard.Frame` (drops border/padding, keeps section `id`).
- [x] Thread optional `bare` prop through `ClaudeSidecarSettings`, `OpenRouterSidecarSettings`, `OmniRouteSidecarSettings`.
- [x] Create `SidecarIntegrationsCard` — one "External Integrations" card with a data-driven `Tabs` switcher, enabled-dot indicators, and first-enabled default tab.
- [x] Replace the three sibling cards in `settings-page.tsx` with the unified card.
- [x] Add `sidecar-integrations-card.test.tsx` covering tab rendering, default-enabled tab, fallback, and tab switching.
- [x] Verify: `npx vitest run` (new + existing sidecar tests) and `bun run build` pass; `openspec validate --specs` passes.
