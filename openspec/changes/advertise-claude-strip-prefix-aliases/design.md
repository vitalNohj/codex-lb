## Context

The Claude catalog lists pinned full models and discovered CLIProxyAPI ids that survive dispatch unchanged. Production's only prefix is `cc/` with strip enabled. Discovered ids are bare (`claude-opus-5-5`). They do not start with `cc/`, so they do not route unless pinned, and the prefixed form fails the same-string check because dispatch removes the prefix.

## Goals / Non-Goals

**Goals:**

- Advertise `<prefix><upstream-id>` for each strip-enabled Claude prefix when that alias dispatches to `<upstream-id>`.
- Keep the same-string check for discovered ids that are not strip-prefix aliases.

**Non-Goals:**

- Advertising an alias that the model profile rewrites (`cc/claude-opus-4-7-high` forwards `claude-opus-4-7`).
- Changing wire-model resolution, pricing, or other providers' catalogs.

## Decisions

1. Build aliases from discovered ids and pinned full models. Skip a base that already begins with a strip prefix so `cp-claude-sonnet` does not become `cp-cp-claude-sonnet`.
2. Admit an alias only when `resolve_sidecar_route` selects Claude and the dispatch model equals the base, case-insensitively.
3. Show the alias when the API key may see either the alias or the base id.

## Risks / Trade-offs

- A CLIProxyAPI catalog that includes a non-Claude id will also gain a `cc/` alias, because that is the same prefix route. The alias still forwards that exact id.
