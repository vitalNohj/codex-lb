## Why

`GET /v1/models` advertises `context_length: 200000` for every external-integration (sidecar) model. The 200k value was a placeholder default from `advertise-sidecar-context-window`, chosen so Cursor would learn some window at all. It is now wrong for most of the catalog:

- Claude Opus 5.5, Opus 4.6-4.8, Fable 5/5.1, Mythos 5, Sonnet 5 and Sonnet 4.6 have 1,000,000-token windows. The sidecar dispatch path already knows this (`_SIDECAR_MAX_TOKENS_BOUNDS` guards output against a 1M window), so the catalog and the dispatcher disagree about the same model.
- OpenRouter, OrcaRouter and most OpenAI-compatible gateways publish each model's real window in their own `/models` entry (`context_length`, `top_provider.context_length`). codex-lb already fetches and caches those entries (`SidecarModel.raw`) and discards the field.

Clients size themselves from the advertised value. Cursor compacts a 1M conversation at 200k. nohjbot, the reviewer that runs through this proxy, bounds its review input by the advertised window and refused a 103-file PR that Opus 5.5 could have read. An operator also cannot correct a sidecar window: `CODEX_LB_MODEL_CONTEXT_WINDOW_OVERRIDES` applies only to registry models.

## What Changes

- Each sidecar entry on `GET /v1/models` resolves one window, in order: an operator `model_context_window_overrides` entry for the advertised id; for Claude sidecar models, the published window from the same canonical-model table dispatch uses; the window in the provider's own catalog entry; the existing 200,000 default.
- A strip-prefix alias (`cc/claude-opus-5-5`) and a dated or dotted id resolve to their canonical model and advertise the same window as the bare id.
- `context_length`, `contextLength` and `capabilities.context_length` stay equal, so one model never advertises two windows.
- No new setting, no dashboard change, no migration. A model with no known window keeps the 200k default.

## Capabilities

### Modified Capabilities

- `model-catalog-compat`: sidecar entries on `/v1/models` advertise the model's real context window when known, instead of a fixed 200,000.

## Impact

- Code: `app/modules/proxy/api.py` (catalog), `app/modules/proxy/claude_sidecar_dispatch.py` (window lookup shared with the output bounds).
- Tests: `tests/integration/test_claude_sidecar_routing.py`, `tests/integration/test_openrouter_sidecar_routing.py`; the sidecar test fakes gain the `raw` field the real `SidecarModel` already has.
- Clients see larger windows for 1M models and provider-reported windows for catalog models. Cursor compacts later on those models, which is the point; the late context-error fallback that emits synthetic usage stays unchanged for anything that still overflows.
