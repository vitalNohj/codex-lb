## Context

`DEFAULT_MODEL_ALIASES` has a Claude block of `fnmatch` patterns such as `*claude-sonnet-5*` and `*claude-opus-4*`. The longest match wins. `*` matches anywhere, so `claude-sonnet-5-5`, `claude-sonnet-5-50`, and `not-claude-sonnet-5-5` all become `claude-sonnet-5`.

That table was added so a sidecar prefix (`cp-claude-opus-4-7`) and a release stamp (`claude-opus-4-5-20251101`) could find a price row. The Claude sidecar wire path later reused the same matcher, so a new catalog id is renamed before CLIProxyAPI sees it. Versioned regexes for Fable 5.1, Opus 5.5, and Sonnet 5.5 exist only to escape that rename.

Routing prefixes are a different mechanism. `resolve_sidecar_route` already strips `cc/`, `cp-`, and `cp_` when the prefix is marked strip. The glob runs after that.

## Goals / Non-Goals

**Goals:**

- Forward a Claude catalog id as itself, with no family-glob edit when a new id appears.
- Keep price and allowlist lookup for a prefix, a `-YYYYMMDD` or `-YYYY-MM-DD` stamp, and a trailing reasoning-effort suffix of an id that already has a price key.
- Keep a trailing release stamp on the forwarded model.
- Keep peeling `thinking`/`reasoning` markers that sit next to an effort token, so `claude-opus-4-7-thinking-high` still forwards as `claude-opus-4-7` with effort `high`.
- Restore a missing `claude-` prefix only when `claude-<id>` is an exact price key (`opus-4-7` to `claude-opus-4-7`).

**Non-Goals:**

- Deleting GPT, OpenRouter, llama, gemini, or the OmniRoute `*claude-3-5-sonnet*` row. That row maps the older bare name to the dated price key `claude-3-5-sonnet-20241022`. It does not match `claude-sonnet-5` or later ids. The wire path no longer consults it.
- Deleting price rows, output-bounds rows, the Sonnet 5.5 full-model pin, or the versioned regexes. Those regexes still normalize dotted `5.5` and `5.1`.
- Adding a bounds row or a price row for every future id. An unknown id is forwarded unchanged, has no price until a row exists, and keeps the client's `max_tokens`.
- Updating or restarting CLIProxyAPI.

## Decisions

1. Delete the Claude family block in `DEFAULT_MODEL_ALIASES`. Do not replace it with a new glob.
2. Put prefix, effort, and date peeling in `app/core/usage/model_ids.py`. Pricing, canonical ids, and the wire path call that helper. Peeling removes one known prefix (`cc/`, `cp-`, `cp_`), one trailing effort token, `thinking` or `reasoning` markers adjacent to that token, and one trailing release date. It does not delete a version segment.
3. The wire resolver stops calling `resolve_model_alias`. A versioned id still normalizes dotted forms. A dated spelling of that id stays dated on the wire. Anything else is forwarded after the peel above.
4. `get_pricing_for_model` tries an exact key, then the versioned id, then the remaining non-Claude aliases, then the peeled Claude identity. The peeled identity must equal a key in the supplied table. A table that only has `claude-sonnet-5` does not price `claude-sonnet-5-5`.
5. `canonical_sidecar_model` uses the peeled identity for bounds and context windows. `claude-sonnet-4-5-20250929` still finds the `claude-sonnet-4-5` bounds row. An id with no bounds row does not borrow another model's window through a substring match.
6. Allowlists already fall through to `canonical_sidecar_model` after pricing aliases. Once the Claude globs are gone, `claude-sonnet-5` admits `cc/claude-sonnet-5` and `claude-sonnet-5-high`, and rejects `claude-sonnet-5-50`.

## Risks / Trade-offs

- [A real model id that ends in `-high` or `-YYYYMMDD`] → Mitigation: only a trailing effort token or a trailing release-date shape is removed, and the date stays on the wire. A longer leftover such as `-50` is kept.
- [An unknown id has no 32k output floor] → Mitigation: the floor stays on the explicit bounds table. Adding a floor is a separate price-and-bounds edit, not a glob edit.
- [`*claude-3-5-sonnet*` still substring-matches for native pricing of that old name] → Mitigation: leave it. It is not on the wire path and does not match current Claude 4 or Claude 5 ids.
- [Historical rows priced through the old glob] → Mitigation: no backfill. New lookups stop collapsing. Already stored costs stay as they are.

## Migration Plan

No schema change. Deploy with the next `codex-lb.service` restart. Rollback is reverting the commit. Do not restart the service as part of this change.

## Open Questions

None.
