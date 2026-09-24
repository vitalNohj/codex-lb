## 1. Resolve one window per sidecar model

- [x] 1.1 Share the Claude sidecar context-window lookup with the output bounds (`sidecar_context_window`), using `canonical_sidecar_model`.
- [x] 1.2 Read the provider catalog window from `SidecarModel.raw` (`context_length`, `context_window`, `top_provider.context_length`; positive non-bool integers only).
- [x] 1.3 Resolve override -> Claude table -> catalog -> 200,000 at every sidecar entry on `GET /v1/models`, including strip-prefix aliases.

## 2. Regression coverage

- [x] 2.1 Claude: bare, `cc/` alias, dated and unknown ids advertise 1M / 1M / 200k / 200k (fails on the previous code).
- [x] 2.2 OpenRouter: `context_length`, `top_provider.context_length`, a bool value (ignored) and an operator override (wins).
- [x] 2.3 Existing sidecar `/v1/models` suites stay green.

## 3. Validation

- [x] 3.1 `openspec validate advertise-real-sidecar-context-windows --strict`
