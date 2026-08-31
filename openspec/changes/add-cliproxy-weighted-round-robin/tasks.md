# Tasks

## 1. Backend

- [x] 1.1 Add `weighted_round_robin` to `ClaudeSidecarRoutingStrategy` and the `_STRATEGY_TO_WIRE` map (`weighted-round-robin`).
- [x] 1.2 Integration tests: GET maps `weighted-round-robin` → `weighted_round_robin`; PUT forwards `weighted_round_robin` → `weighted-round-robin`; `bogus` still 422.

## 2. Frontend

- [x] 2.1 Add `weighted_round_robin` to `ClaudeSidecarRoutingStrategySchema`.
- [x] 2.2 Add Weighted round robin to the CLIProxyAPI routing dropdown and update the help line (weight, default 1, top priority group).
- [x] 2.3 Frontend tests: option exists; selecting it PUTs `weighted_round_robin`; live `weighted_round_robin` shows as selected.

## 3. Validation

- [x] 3.1 `openspec validate add-cliproxy-weighted-round-robin --strict`.
- [x] 3.2 Targeted backend pytest + frontend vitest.
