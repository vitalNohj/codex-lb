## Why

The Settings page still labels the sidecar configuration sections with
sidecar-specific names, while the dashboard now presents these surfaces as
provider integrations. The settings labels should use the same operator-facing
integration language.

## What Changes

- Rename the Claude sidecar settings section heading to `CLIProxyAPI Integration`.
- Rename the OpenRouter sidecar settings section heading to `OpenRouter Integration`.
- Rename the OmniRoute sidecar settings section heading to `OmniRoute Integration`.
- Keep the existing route anchor, setting keys, and API behavior unchanged.

## Impact

- Affects dashboard settings copy only.
- No backend behavior, persistence, or API contract changes.
