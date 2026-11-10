## 1. Retain catalog capabilities

- [x] 1.1 Parse typed Claude capabilities from the existing models.dev payload; verify exact-id and malformed-field parser tests.
- [x] 1.2 Extend the existing cache/refresh lifecycle with optional capabilities; verify partial outage, legacy cache, bundle precedence, and offline restart tests.

## 2. Apply capabilities

- [x] 2.1 Derive missing Claude output bounds without changing fixed rows or guards; verify Fable 5.2-style, fixed, unknown, and unavailable-catalog dispatch tests.
- [x] 2.2 Advertise catalog input modalities and vision flags for Claude sidecar rows and aliases; verify HTTP model-list tests and existing fallback tests.

## 3. Validate and deliver

- [x] 3.1 Check Shared key admission and cache-write provenance without changing pricing; record the evidence in the PR body.
- [x] 3.2 Run affected tests, lint, type checks, and strict OpenSpec validation; review the complete diff and document any check not run.
