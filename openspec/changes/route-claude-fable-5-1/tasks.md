## 1. Aliases, pricing, bounds

- [x] 1.1 Add `claude-fable-5-1` to `DEFAULT_PRICING_MODELS` ($10 / $0.25 cache-hit / $50) and bounded model identity recognition without extending legacy pricing globs.
- [x] 1.4 Preserve GPT-6 Astra native tier pricing and date/prefix identity recognition from production.
- [x] 1.2 Add `_SIDECAR_MAX_TOKENS_BOUNDS` for `claude-fable-5-1` matching Fable 5 (floor 32768, cap 128000, context 1M).
- [x] 1.3 Unit tests: 5.1 / 5-1 / prefixed / thinking-max ids forward `claude-fable-5-1`; plain Fable 5 stays `claude-fable-5`; 5.1 cache-hit pricing; 5.1 max_tokens floor.

## 2. Validation

- [x] 2.1 `openspec validate route-claude-fable-5-1 --strict`
- [x] 2.2 Pricing, model-profile, payload and bounded-identity unit tests plus mocked chat-routing integration tests pass (211 tests).
- [x] 2.3 Mocked API regression fails on current main and passes after reconciliation. External catalog rates remain authoritative for sidecar costs.
- [x] 2.4 Expanded routing, pricing, quota propagation and model-exclusion regression suite passes (2,076 tests).

## 3. Review follow-up

- [x] 3.1 Keep the legacy family fallback when a supplied price table lacks the resolved version, so cost is never silently dropped.
- [x] 3.2 Resolve the version in API-key access control so a `claude-fable-5` allowlist cannot reach separately priced Fable 5.1.
- [x] 3.3 Regressions for both, failing before the fixes and passing after.
