## 1. Settings placement

- [x] 1.1 Extract the alias editor from `RoutingSettings` into an `AliasSettings` card using the shared settings section shell.
- [x] 1.2 Add a `Model aliasing` Settings navigation entry and section outside the Advanced group.
- [x] 1.3 Remove the alias editor from the Advanced routing settings section.

## 2. Verification

- [x] 2.1 Cover navigation, card placement, read-only disabling, and existing alias edits (pool reorder/add/remove, add-alias, duplicate-name guard, catalog context length, server pool rejection, health polling) with Vitest.
- [x] 2.2 Run frontend typecheck, ESLint, and the settings test suites.
