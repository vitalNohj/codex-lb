## Why

Cursor sends `cc/claude-fable-5-1` (Claude Fable 5.1). The Claude sidecar model profile canonicalizes wire models through `DEFAULT_MODEL_ALIASES`, and the family glob `*claude-fable-5*` also matches `5.1` / `5-1`. Every 5.1 request is forwarded to CLIProxyAPI as `claude-fable-5`. A mocked `/v1/chat/completions` regression reproduces this on current main. The preserved production proposal identifies `claude-fable-5-1` as the intended CLIProxyAPI wire id.

## What Changes

- Add canonical `claude-fable-5-1` pricing (same $10 / $50 as Fable 5; cache-hit $0.25)
- Recognize Fable 5.1 with a bounded model-identity resolver before legacy family aliases, without extending `DEFAULT_MODEL_ALIASES`
- Preserve GPT-6 Astra native tier and long-context rates from the same production edits
- Keep external integration prices catalog-owned, including Claude sidecar request-log costs
- Forward the CLIProxyAPI / Anthropic id `claude-fable-5-1` (not OpenRouter `anthropic/claude-fable-5.1`)
- Apply the same 32k/128k/1M max-tokens bounds as Fable 5
- Keep `claude-fable-5` traffic on Fable 5

## Capabilities

### New Capabilities

- none

### Modified Capabilities

- `chat-completions-compat`: Claude sidecar wire model for Fable 5.1 MUST be `claude-fable-5-1`
- `api-keys`: native cost accounting preserves the [reconciled Astra and Fable 5.1 rates](../../specs/api-keys/spec.md#requirement-gpt-6-astra-native-usage-cost-pricing-preserves-reconciled-rates)

## Impact

- Code: `app/core/usage/pricing.py`, `app/modules/proxy/claude_sidecar_dispatch.py`, `app/modules/proxy/sidecar_model_profiles.py`, `app/core/usage/model_ids.py`
- Tests: `tests/unit/test_pricing.py`, `tests/unit/test_sidecar_model_profiles.py`, `tests/unit/test_claude_sidecar_dispatch.py`
- Live: requires `codex-lb.service` restart
