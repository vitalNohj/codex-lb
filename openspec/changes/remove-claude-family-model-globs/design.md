## Context

`DEFAULT_MODEL_ALIASES` had a Claude block of `fnmatch` patterns such as `*claude-sonnet-5*` and `*claude-opus-4*`. `*` matches anywhere, so `claude-sonnet-5-5` became `claude-sonnet-5`. That table was added so a sidecar prefix and a release stamp could find a price row. The wire path reused it, so a new catalog id was renamed before CLIProxyAPI saw it.

The replacement peel (one effort token, an adjacent `thinking` marker, one release date, dotted-version regexes, and restoring a missing `claude-` prefix) is still a second model identity. Live request logs are `cc/` plus a catalog id. Date stamps, `-thinking-high`, and `-high` do not appear. Dotted `claude-fable-5.1` does appear, and it is a different string from `claude-fable-5-1`.

Routing prefixes are a different mechanism. `resolve_sidecar_route` strips a prefix only when that prefix is marked strip. Full-model matches are forwarded as typed. `GET /v1/models` advertises pinned full models and upstream ids that survive that route.

## Goals / Non-Goals

**Goals:**

- Forward the routed Claude id as itself.
- Let a discovered upstream id show up in model discovery when dispatch sends that id.
- Let a pinned full model show up for the API keys that allow it.
- Price and bound an id only when it exactly matches a row after one leading `cc/`, `cp-`, or `cp_` prefix.

**Non-Goals:**

- Deleting GPT, OpenRouter, llama, gemini, or the OmniRoute `*claude-3-5-sonnet*` row. That row maps the older bare name to `claude-3-5-sonnet-20241022` for native price lookup. It does not match current Claude 4 or Claude 5 ids, and the wire path does not consult it.
- Deleting price rows, output-bounds rows, or the Sonnet 5.5 and Opus 5.5 full-model pins.
- Adding a bounds row or a price row for every future id.
- Adding a code alias from `claude-fable-5.1` to `claude-fable-5-1`. Dashboard model aliasing is the operator rename when a catalog id differs from the id they want.
- Updating or restarting CLIProxyAPI.

## Decisions

1. Delete the Claude family block in `DEFAULT_MODEL_ALIASES`. Do not replace it with a new glob or a Claude version regex.
2. The wire profile does not rename the model and does not read effort from the model name. Routing owns prefix stripping. Operator `default_reasoning_effort` still forces the configured effort.
3. `resolve_versioned_model_id` keeps the GPT-6 matcher only.
4. `get_pricing_for_model` exact-matches, then the GPT-6 id, then the remaining non-Claude aliases, then the same id with one leading `cc/`, `cp-`, or `cp_` removed. A dotted, dated, or suffixed id that is not itself a key has no Claude price.
5. Output bounds and the static context window use that same prefix-stripped exact id. An id with no bounds row keeps the client's `max_tokens` and the 200k catalog default.
6. Allowlists use the routed wire model. A grant of `claude-sonnet-5-5` admits `cc/claude-sonnet-5-5` and rejects `claude-sonnet-5.5`, `claude-sonnet-5-50`, and `claude-sonnet-5-5-thinking-max`.
7. Catalog advertisement still hides an id whose route would send a different string (`cp-claude-sonnet` with `cp-` strip). It no longer hides `claude-opus-4-7-high`, because that id is forwarded unchanged. Pinned full models stay advertised.

## Risks / Trade-offs

- [Dotted `cc/claude-fable-5.1` no longer reaches `claude-fable-5-1`] → The prefix sends `claude-fable-5.1`. Upstream answers if it has that id. A dashboard alias is how to connect it to the hyphen id.
- [A dated id no longer uses the undated price or 32k floor] → The dated string is a different id. Add a row for that string if it needs a price or a floor.
- [An unknown id has no 32k output floor] → The floor stays on the explicit bounds table.
- [`*claude-3-5-sonnet*` still substring-matches for native pricing of that old name] → Leave it. It is not on the wire path.
- [Historical rows priced through the old glob or peel] → No backfill. New lookups stop collapsing. Already stored costs stay as they are.

## Migration Plan

No schema change. Deploy with the next `codex-lb.service` restart. Rollback is reverting the commit. Do not restart the service as part of this change.

## Open Questions

None.
