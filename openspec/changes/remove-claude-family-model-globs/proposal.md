## Why

Claude family globs in `DEFAULT_MODEL_ALIASES` rewrite a new catalog id into an older family id. Adding a model means editing the glob, the price row, and the CLIProxyAPI catalog. The glob is the step that makes a longer id unusable until the code changes.

## What Changes

- Remove the Claude family globs (`*claude-sonnet-5*`, `*claude-opus-4*`, and the other `*claude-<family>*` rows in that block) from `DEFAULT_MODEL_ALIASES`
- Forward a Claude sidecar model as itself, except for a routing prefix, a reasoning-effort suffix, and dotted versions that `resolve_versioned_model_id` already recognizes
- Price and allow a prefixed, date-stamped, or effort-suffixed spelling only when the remainder is an exact existing price key
- **BREAKING**: a longer id no longer inherits a shorter family's price or allowlist entry. `claude-sonnet-5-50` and `not-claude-sonnet-5-5` no longer price or authorize as `claude-sonnet-5`. A price table that has only the shorter key no longer prices the longer id
- Leave GPT, OpenRouter, and OmniRoute alias patterns in place, including `*claude-3-5-sonnet*` which maps that older OmniRoute name onto its dated price key
- Leave the Sonnet 5.5, Opus 5.5, and Fable 5.1 versioned identities, price rows, output bounds, and full-model pin in place

## Capabilities

### New Capabilities

- none

### Modified Capabilities

- `chat-completions-compat`: the Claude sidecar MUST forward a catalog id without folding it into a shorter family through `DEFAULT_MODEL_ALIASES`
- `api-keys`: native Claude price lookup and allowlists MUST match an existing key after prefix, date, and effort decoration, and MUST NOT grant a longer id the shorter family's price or access

## Impact

- Code: `app/core/usage/pricing.py`, `app/core/usage/model_ids.py`, `app/modules/proxy/sidecar_model_profiles.py`
- Tests: pricing, sidecar profiles, versioned identity, request policy, and the discovered-model catalog round trip
- A future catalog id is forwarded as itself with no glob edit. It has no price until a row is added, and no output floor until a bounds row exists
- Live: requires a `codex-lb.service` restart before the new code runs. CLIProxyAPI catalog updates stay out of scope
