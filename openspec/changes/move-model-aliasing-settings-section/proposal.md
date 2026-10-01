## Why

The model alias and alias-pool editor sits at the bottom of the Advanced
routing settings, so operators have to expand Advanced and scroll past every
routing control to manage aliases. Aliases are an everyday configuration
surface (they are advertised on `GET /v1/models` and drive failover pools), so
they deserve a first-class place on the Settings page.

## What Changes

- Add a `Model aliasing` entry to the Settings section navigation and a
  dedicated settings card that holds the existing alias editor.
- Remove the alias editor from the Advanced routing settings section, so it is
  rendered exactly once.
- Keep editing, saving (patched `modelAliases` / `customAliasCatalog` with
  `expectedVersion`), conflict handling, inline pool-rejection errors, health
  polling, read-only disabling, and accessible names unchanged.

## Capabilities

### New Capabilities

- None

### Modified Capabilities

- `frontend-architecture`: the Settings page requirement lists model aliasing
  as a core section with its own navigation entry and card instead of part of
  the Advanced routing section.

## Impact

- Frontend only: Settings page layout, a new `AliasSettings` component
  extracted from `RoutingSettings`, i18n strings, and tests.
- No backend, API, schema, or data-format change.
