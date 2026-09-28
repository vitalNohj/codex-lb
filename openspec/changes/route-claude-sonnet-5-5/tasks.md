## 1. Identity, pricing, wire model

- [x] 1.1 Add bounded `claude-sonnet-5-5` recognition without a new pricing glob, and add the $2 / $0.20 / $10 static row.
- [x] 1.2 Confirm hyphen, dotted, prefixed, thinking-suffix, and `-YYYYMMDD` forms forward as Sonnet 5.5. Unversioned Sonnet 5 stays `claude-sonnet-5`.
- [x] 1.3 Add Sonnet 5.5 output bounds: floor 32768, cap 128000, context 1M.

## 2. Full-model pin

- [x] 2.1 Append `claude-sonnet-5-5` to stored CLIProxyAPI full models when absent. Downgrade removes that id only from rows this upgrade appended.
- [x] 2.2 A settings save that removes `claude-sonnet-5-5` keeps the row marked as processed (a replay does not re-add it); a save that adds it back deletes that row's pin ownership (downgrade keeps the operator's pin).

## 3. Validation

- [x] 3.1 `openspec validate route-claude-sonnet-5-5 --strict`
- [x] 3.2 Unit and migration tests cover wire model, pricing, allowlist, bounds, and the full-model pin.
