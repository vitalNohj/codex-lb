## Why

An OrcaRouter or OpenRouter integration that is enabled with no usable API key
refuses every request locally (`*_not_configured`, or a skipped pool target).
Discovery still treated "enabled" as "available": `GET /v1/models` listed its
models, and a pool alias whose every target was keyless, and both
`GET /v1/models` and the dashboard model picker polled the keyless upstream's
catalog. A client that picks an advertised model gets a 503 it could not have
predicted, and the picker offers models for aliases and API-key allowances that
cannot be served. OpenCode Go already requires a usable key for discovery; the
other two key-required integrations did not.

## What Changes

- `GET /v1/models` and `GET /api/models` list OrcaRouter and OpenRouter models,
  and poll those upstreams, only when the integration has a usable key.
- A model alias is advertised on `GET /v1/models` only while at least one target
  is visible and not owned by a keyless OrcaRouter, OpenRouter, or OpenCode Go
  integration.
- Routing is unchanged: an enabled integration still owns its models without a
  key, so a request for one is refused locally rather than falling through to
  another provider.
