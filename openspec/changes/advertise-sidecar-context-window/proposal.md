## Why

Cursor's local-provider discovery reads `GET /v1/models` to learn each model's
context window and uses it to decide when to auto-summarize/compact a
conversation before it overflows. Registry (GPT/Codex) models are listed with
`context_length`, `contextLength`, and `capabilities.context_length`, so Cursor
compacts correctly. Sidecar models (Claude/cliproxyapi `cp-*`, OpenRouter, and
OmniRoute) are listed with only `id`, `created`, `owned_by`, and `api_types` —
no context window.

As a result, when a conversation runs on a sidecar model, Cursor never learns
the window and lets the prompt grow unbounded (observed climbing past 100k
tokens). The only sidecar compaction trigger is reactive — a synthetic
1,000,000-token usage response emitted when the upstream returns a
context-length error — but the Claude upstream accepts large prompts, so that
error never arrives and compaction never fires. The conversation eventually
hard-fails with "max context length exceeded."

## What Changes

- Advertise an input context window for all sidecar models (Claude, OpenRouter,
  OmniRoute) on `GET /v1/models`, mirroring the capability/context fields
  registry models already expose (`context_length`, `contextLength`,
  `capabilities.context_length`).
- Use a default window of 200000 for sidecar models.
- Keep registry-model metadata unchanged.

## Impact

- Affected spec: `model-catalog-compat`.
- Affected code: `app/modules/proxy/api.py`,
  `tests/integration/test_claude_sidecar_routing.py`,
  `tests/integration/test_openrouter_sidecar_routing.py`,
  `tests/integration/test_omniroute_sidecar_routing.py`.
- No database or dashboard changes.
