## Why

CLIProxyAPI already advertises `claude-opus-5-5`, but the Claude sidecar canonicalizes wire models through the family glob `*claude-opus-5*`. Every Opus 5.5 request is forwarded as `claude-opus-5` and priced at Opus 5 rates ($5 / $0.50 / $25). Opus 5.5 shipped on 2026-09-22 at $4 / $0.20 / $20. Sonnet 5.5 and Haiku 5.5 are not released.

## What Changes

- Recognize `claude-opus-5-5` with a bounded model identity before the Opus 5 family alias, without adding a new pricing glob
- Forward the CLIProxyAPI id `claude-opus-5-5` for hyphen, dotted, prefixed, and reasoning-suffix forms
- Price that identity at the published Opus 5.5 rates ($4 input / $0.20 cache-hit / $20 output)
- Apply 32,768 / 128,000 / 1,000,000 output bounds
- Append `claude-opus-5-5` to stored CLIProxyAPI full models when it is absent
- Keep `claude-opus-5` on Opus 5

## Capabilities

### New Capabilities

- none

### Modified Capabilities

- `chat-completions-compat`: Claude sidecar wire model for Opus 5.5 MUST be `claude-opus-5-5`, and the stored full-model list MUST gain that id on upgrade
- `api-keys`: native cost accounting MUST price Opus 5.5 separately from Opus 5, and an Opus 5 allowlist MUST NOT admit Opus 5.5

## Impact

- Code: `app/core/usage/model_ids.py`, `app/core/usage/pricing.py`, `app/modules/proxy/sidecar_model_profiles.py`, `app/modules/proxy/claude_sidecar_dispatch.py`
- Migration: append `claude-opus-5-5` to `dashboard_settings.claude_sidecar_full_models_json`
- Tests: pricing, versioned identity, sidecar profile, chat payload, routing, and the full-model migration
- Live: requires a `codex-lb.service` restart before the new code and migration run
