## Overview

Ollama Cloud sidecar routing is implemented as a first-class sidecar provider beside CLIProxyAPI, OpenRouter, and OmniRoute. Configuration lives in `DashboardSettings`; request routing uses the unified sidecar resolver; dashboard status/model discovery uses a dedicated Ollama module; and Chat Completions dispatch converts between the OpenAI-compatible request/response shape and the Ollama SDK chat shape.

Local proxy/tunnel mode is intentionally deferred. Cloud mode has a stable base URL, bearer API-key authentication, and a server-to-server streaming path that fits the existing sidecar architecture. Local mode would require separate operator-facing contracts for tunnels, trust boundaries, endpoint allowlisting, and stream reliability.

## SDK And Authentication

The backend uses the official `ollama-python` SDK, specifically `ollama.AsyncClient`, from a small wrapper in `app/core/clients/ollama_sidecar.py`. The wrapper owns:

- Base URL normalization, with Cloud default `https://ollama.com`.
- Optional bearer auth headers.
- SDK error conversion into codex-lb sidecar errors.
- Cloud-only model filtering.
- In-memory model-list caching with the configured TTL.

The Ollama API key is stored encrypted in dashboard settings. Outbound calls send it as:

```text
Authorization: Bearer <key>
```

The raw API key is never returned by Settings, dashboard status, model-list, test-connection, request-log, or error responses.

## Cloud Model Discovery Filter

The model discovery endpoint calls the SDK list method and normalizes IDs from dictionary keys or object attributes named `model` or `name`.

Only cloud model IDs are returned to the dashboard. A model is considered cloud-based when:

- `model_id.endswith("-cloud")`, or
- `":cloud"` appears in `model_id`, or
- the ID is present in the curated Cloud allowlist.

The initial curated allowlist is seeded from official Cloud examples:

- `deepseek-v3.1:671b-cloud`
- `gpt-oss:20b-cloud`
- `gpt-oss:120b-cloud`
- `kimi-k2:1t-cloud`
- `qwen3-coder:480b-cloud`
- `kimi-k2-thinking`

`kimi-k2-thinking` is included even though it lacks a textual `cloud` marker because Ollama documents it as a Cloud model. Non-cloud local IDs such as `llama3.2` are hidden from discovery.

## Routing And Model Identity

Ollama participates in the unified sidecar resolver after OmniRoute in the deterministic provider order. Full model exact match is evaluated before prefix routing across all enabled integrations. Prefix routing uses the shared per-prefix strip flag.

The request's effective model remains the client-facing model for API-key validation, request-limit reservations, and request logs. The resolver's wire model is forwarded to Ollama.

Ollama is not added to `/v1/responses` in this change.

## Chat Completions Adaptation

The Ollama dispatch path converts accepted OpenAI Chat Completions fields into an Ollama chat payload:

- `model` uses the resolver's wire model.
- Supported message roles are preserved.
- String content is forwarded directly; unsupported rich content is reduced only where the existing request schema already accepts it.
- Function tools are converted to Ollama tool definitions.
- JSON response formats map to Ollama `format`.
- `temperature`, `top_p`, `max_tokens`, and stop sequences map into Ollama `options`.

Non-streaming Ollama responses are converted back into OpenAI Chat Completions responses. Streaming responses are emitted as OpenAI-style SSE chunks, including a first assistant-role chunk, content deltas, tool-call deltas when available, optional usage, and `data: [DONE]` on success.

## Dashboard And Settings UI

Ollama Settings UI is one tab inside the existing "External Integrations" card. The implementation adds `OllamaSidecarSettings` with `bare?: boolean` and one `tabs` array entry in `frontend/src/features/settings/components/sidecar-integrations.tsx`. The existing card, tab list, tab content layout, and Settings page structure are not otherwise changed.

The Ollama tab exposes enable, base URL, API key, prefixes, full models, discovered cloud models, timeouts, status, and test-connection behavior through the same `SidecarIntegrationCard` compound component used by the other integrations.

## Observability And Costs

Ollama request logs use `source="ollama_sidecar"` and normal `transport="http"` presentation. The dashboard account/provider label is `Ollama`.

Token usage is recorded from Ollama response usage counters when available:

- `prompt_eval_count` -> input tokens
- `eval_count` -> output tokens

`cost_usd` remains `NULL` unless a real pricing entry exists. The implementation must not invent zero-cost rows for paid models without pricing evidence. Existing reference-cost logic may compute `reference_cost_usd` where applicable.

## Failure Modes

- Disabled integration: route is not considered and dashboard status is `disabled`.
- Enabled without API key: dashboard status/test/models return missing-key state without network calls.
- Unauthorized upstream: dashboard status records `unauthorized`; chat dispatch returns an OpenAI-compatible upstream error.
- Transport failure: dashboard status records `unreachable`; chat dispatch returns stable `ollama_sidecar_unavailable` behavior.
- Upstream response error: dispatch maps `ollama.ResponseError` to stable `ollama_sidecar_error` behavior without leaking secrets.
