# Model catalog

`app/core/models/catalog.py::resolve_model()` is the shared metadata and price
boundary for discovery, context limits, settlement, request logs, and usage.
It does not make network calls. The existing source adapters own refresh and
storage; model names do not select a different price table in each consumer.

## Sources and precedence

1. `app/core/models/cliproxy_snapshot.json` vendors
   [router-for-me/models](https://github.com/router-for-me/models/blob/main/models.json).
   The metadata scheduler refreshes the raw GitHub file hourly. It validates a
   complete response before publication, persists a last-good cache in the data
   directory, and keeps the cache or bundled snapshot on failure.
2. The existing live **Codex account catalog** supplies subscription capabilities.
   Its positive `max_context_window` is the usable input ceiling, not the smaller
   default `context_window`. The local bootstrap retains its previous windows
   until live evidence is available. An authoritative account catalog, not this
   metadata catalog, still controls which models an account can serve.
3. Existing OpenAI price snapshots/refreshes and the provider-scoped external
   price store supply prices. OpenRouter, OrcaRouter and CLIProxyAPI remain
   separate price namespaces. An unknown external price stays unknown; it must
   never inherit a same-named subscription price. Dashboard model sources keep
   their own explicit rates and capabilities.
4. `config/models.local.json` supplies exact-id corrections and compatibility
   defaults. A local correction wins over a source field; migrated
   `fallback_price` values only fill missing external prices, so refreshes still
   update existing models. Legacy Claude fallback
   bounds do not replace a window explicitly published by the serving catalog,
   or a provider row's explicit modalities. Dashboard/env context overrides
   retain their existing final precedence and real upstream ceiling clamp.

Both model-list formats expose `catalog_provenance`: one source label for each
resolved field, including individual `price.*` fields. A model's price describes
its serving route, including cache reads/writes, published 1-hour/12-hour writes,
long-context rates, Priority/Fast, Flex, and Batch when known. Alias pools with
different target prices intentionally have no single published price.

## Add or correct a model

Usually no code or local entry is needed: the upstream metadata and price
sources add it. Routing still needs an existing account or sidecar that can
serve the model; a metadata entry does not grant account access.

For a missing model, add **one entry** under `models` in
`config/models.local.json`:

```json
"example-model": {
  "provider": "example",
  "context_window": 200000,
  "max_output_tokens": 32000,
  "thinking_levels": ["low", "high"],
  "input_modalities": ["text", "image"],
  "price": {
    "input_per_1m": 2,
    "cached_input_per_1m": 0.2,
    "output_per_1m": 10
  }
}
```

All fields except the id are optional. `price` needs input and output rates for
a model with no upstream price. It replaces the complete rate record, including
which tiers are unknown. To correct just one existing rate, use
`"price_overrides": {"output_per_1m": 12}`. Use `provider_prices` for a correction
restricted to an external pricing provider, for example
`"provider_prices": {"cliproxy": {"input_per_1m": 2, "output_per_1m": 10}}`.
The `ModelPrice` type lists all supported rate names. Rates are USD per million
tokens. `aliases` holds legacy billing spellings/globs; aliases must not infer
capabilities for a different Claude release. `native_aliases: true` also accepts
OpenAI/Codex prefixes and dated native spellings. `native_suffixes` adds bounded
effort/speed suffixes; `prefer_canonical_price` prevents stale alias rows from
replacing an official correction. The optional `codex` object
contains bootstrap presentation/entitlement metadata, not a second price table.
Use `capability_providers` to restrict a capability correction to named serving
integrations, for example `["subscription", "cliproxy"]`. An OpenAI API model
served by another provider must not inherit a subscription-only input ceiling.
`respect_upstream_ceiling` keeps a lower real account ceiling when a verified
local default supplies a larger general window.
Migrated `legacy_sidecar_bounds` apply only to CLIProxyAPI/native fallback paths;
other providers keep their own published limits. Remove that legacy flag when
replacing a fallback with an explicit correction. Restart the application after
changing the local file.

## Compatibility

The migration fixture freezes all 159 active price records after the GPT-6.2
change merged, 10 Codex
bootstrap entries, and 14 Claude bounds. Their served prices/windows stay the
same. The verified GPT-6.1 Sol input window is corrected to **872,000**. The
already merged GPT-6.2 Sol/Astra data now lives here too: 872K input ceilings,
128K output fallback, full Standard/Priority/Batch and 12-hour write rates, and
no invented Flex tier. A live
Codex catalog's declared ceiling also replaces its smaller client default.
Newly available exact-id upstream metadata also fills formerly unknown
capabilities (for example Claude Opus 5), using the existing output-bound rules.
The old separate fallback table disagreed with the active snapshot for GPT-5.6
Sol (5/30 vs. 4/20 input/output), some chat Priority rates, and GPT-5.4 Pro Flex.
The catalog preserves the active settlement snapshot, not those stale fallbacks.
