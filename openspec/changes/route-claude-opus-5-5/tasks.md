## 1. Identity, pricing, wire model

- [x] 1.1 Add bounded `claude-opus-5-5` recognition without a new pricing glob, and add the $4 / $0.20 / $20 static row.
- [x] 1.2 Preserve every versioned Claude id on the sidecar wire path, including dotted, prefixed, thinking-suffix, and `-YYYYMMDD` forms. Opus 5 stays `claude-opus-5`.
- [x] 1.3 Add Opus 5.5 output bounds: floor 32768, cap 128000, context 1M.

## 2. Full-model pin

- [x] 2.1 Append `claude-opus-5-5` to stored CLIProxyAPI full models when absent. Downgrade removes that id only from rows this upgrade appended.

## 3. Validation

- [x] 3.1 `openspec validate route-claude-opus-5-5 --strict`
- [x] 3.2 Unit and migration tests cover wire model, pricing, allowlist, bounds, and the full-model pin.
