## Why

Claude family globs in `DEFAULT_MODEL_ALIASES` rewrite a new catalog id into an older family id. The peel that replaced them (effort suffixes, release dates, dotted versions, and a restored `claude-` prefix) is a second identity system. Prefix routing and full-model discovery already do the job.

## What Changes

- Remove the Claude family globs (`*claude-sonnet-5*`, `*claude-opus-4*`, and the other `*claude-<family>*` rows in that block) from `DEFAULT_MODEL_ALIASES`
- Forward the model id that sidecar routing produced. A configured strip prefix is the only removal. A dotted spelling, a release date, and a thinking or effort suffix stay on the id and go upstream as typed
- Price, allow, and apply output bounds only when that forwarded id exactly matches a row. One leading `cc/`, `cp-`, or `cp_` prefix still finds the same row, because that is the routing prefix, not a second model name
- **BREAKING**: `claude-sonnet-5.5`, `claude-opus-4-7-thinking-high`, and `claude-opus-4-5-20251101` no longer become `claude-sonnet-5-5`, `claude-opus-4-7`, or `claude-opus-4-5`. They are forwarded as themselves. They have no price and no output floor unless that exact string is a row. Upstream returns its own error when it does not have the id
- A discovered upstream id is advertised when dispatch forwards that same id. A full model pinned on the integration is advertised for the API keys that allow it. `cp-claude-sonnet` stays hidden when `cp-` strips, because the request would be sent as `claude-sonnet`
- Leave GPT, OpenRouter, and OmniRoute alias patterns in place, including `*claude-3-5-sonnet*`, which maps that older OmniRoute name onto its dated price key and does not run on the wire path
- Leave the Sonnet 5.5, Opus 5.5, and Fable 5.1 exact price rows, output bounds, and full-model pins in place. They match those exact ids only

## Capabilities

### New Capabilities

- none

### Modified Capabilities

- `chat-completions-compat`: the Claude sidecar MUST forward the routed id unchanged, and MUST advertise a discovered id that dispatch forwards as itself
- `api-keys`: native Claude price lookup and allowlists MUST exact-match after one routing prefix, and MUST NOT fold a dotted, dated, or effort-suffixed spelling into another id

## Impact

- Code: `app/core/usage/pricing.py`, `app/core/usage/model_ids.py`, `app/modules/proxy/sidecar_model_profiles.py`
- Tests: pricing, sidecar profiles, versioned identity, request policy, dispatch bounds, and the discovered-model catalog round trip
- A future catalog id is forwarded as itself. It has no price until a row is added, and no output floor until a bounds row exists. A spelling that differs from the upstream id is connected with dashboard model aliasing, not a new regex
- Live: requires a `codex-lb.service` restart before the new code runs. CLIProxyAPI catalog updates stay out of scope
