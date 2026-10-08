## 1. Pricing and bounds

- [x] 1.1 Add the tiered `claude-haiku-5-5` static row with source comments.
- [x] 1.2 Correct the Sonnet 5.5 cache-hit rate to $0.10.
- [x] 1.3 Add Haiku 5.5 output bounds: floor 32768, cap 128000, context 1M.

## 2. Full-model pin

- [x] 2.1 Append `claude-haiku-5-5` to stored CLIProxyAPI full models when absent, with ownership-tracked downgrade.
- [x] 2.2 Settings saves update the Haiku 5.5 ownership table the same way as the Opus and Sonnet tables.

## 3. Validation

- [x] 3.1 `openspec validate route-claude-haiku-5-5 --strict`
- [x] 3.2 Tests cover both price tiers, the 100,000 boundary, lookalike ids, bounds, and the migration.
