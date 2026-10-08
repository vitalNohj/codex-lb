## Why

Anthropic released Claude Haiku 5.5 on 2026-10-07 as `claude-haiku-5-5`. codex-lb has no price row, output bounds, or full-model pin for it, so it is not advertised on the CLIProxyAPI sidecar and native cost accounting cannot price it. Its price is also tiered by prompt length, unlike earlier Haiku models.

## What Changes

- Price `claude-haiku-5-5` with the existing long-context tier: $0.10 input / $0.01 cache-hit / $0.50 output per 1M tokens up to 100,000 prompt tokens, and $0.50 / $0.05 / $2.50 for the whole request above that
- Apply 32,768 / 128,000 / 1,000,000 output bounds
- Append `claude-haiku-5-5` to stored CLIProxyAPI full models when it is absent
- Correct the Sonnet 5.5 cache-hit rate from $0.20 to the published $0.10

## Capabilities

### New Capabilities

- none

### Modified Capabilities

- `chat-completions-compat`: Claude sidecar forwards `claude-haiku-5-5` unchanged with its output bounds, and the stored full-model list gains that id on upgrade
- `api-keys`: native cost accounting resolves `claude-haiku-5-5` with tiered rates, and Sonnet 5.5 cache hits cost $0.10

## Impact

- Code: `app/core/usage/pricing.py`, `app/modules/proxy/claude_sidecar_dispatch.py`, `app/modules/settings/repository.py`, `app/db/models.py`
- Migration: `20261007_000000_pin_claude_haiku_5_5_full_model` appends the id and records ownership in `claude_haiku_5_5_pin_ownership`
- Tests: pricing tiers and the 100,000 boundary, sidecar bounds, and the full-model migration
- Live: requires a `codex-lb.service` restart. CLIProxyAPI serves the id once its remote catalog lists it (added upstream 2026-10-08).
