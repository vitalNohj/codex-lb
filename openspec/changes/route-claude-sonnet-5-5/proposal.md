## Why

Anthropic released Claude Sonnet 5.5 on 2026-09-28 as `claude-sonnet-5-5`. The Claude sidecar canonicalizes wire models through the family glob `*claude-sonnet-5*`. Every Sonnet 5.5 request is forwarded as `claude-sonnet-5`.

## What Changes

- Recognize `claude-sonnet-5-5` with a bounded model identity before the Sonnet 5 family alias, without adding a new pricing glob
- Forward the Anthropic id `claude-sonnet-5-5` for hyphen, dotted, prefixed, and reasoning-suffix forms
- Price that identity at the published Sonnet 5.5 rates stored by this table ($2 input / $0.20 cache-hit / $10 output)
- Apply 32,768 / 128,000 / 1,000,000 output bounds
- Append `claude-sonnet-5-5` to stored CLIProxyAPI full models when it is absent
- Keep `claude-sonnet-5` on Sonnet 5

## Capabilities

### New Capabilities

- none

### Modified Capabilities

- `chat-completions-compat`: Claude sidecar wire model for Sonnet 5.5 MUST be `claude-sonnet-5-5`, and the stored full-model list MUST gain that id on upgrade
- `api-keys`: native cost accounting MUST resolve Sonnet 5.5 as `claude-sonnet-5-5`, and a Sonnet 5 allowlist MUST NOT admit Sonnet 5.5

## Impact

- Code: `app/core/usage/model_ids.py`, `app/core/usage/pricing.py`, `app/modules/proxy/claude_sidecar_dispatch.py`, `app/modules/settings/repository.py`
- Migration: append `claude-sonnet-5-5` to `dashboard_settings.claude_sidecar_full_models_json`
- Tests: pricing, versioned identity, sidecar profile, chat payload, routing, and the full-model migration
- Live: requires a `codex-lb.service` restart before the new code and migration run. CLIProxyAPI does not list `claude-sonnet-5-5` until its remote catalog includes the id.
