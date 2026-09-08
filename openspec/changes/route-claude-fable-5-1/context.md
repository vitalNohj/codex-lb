# Production source reconciliation

## Scope

Preserve the native Astra pricing and Fable 5.1 routing behavior present in the production source edits while incorporating the already-merged rate-limit propagation and per-account model-exclusion changes. No deployment mechanism or unrelated provider behavior changes are included.

## Identity and pricing ownership

The production implementation extended legacy substring pricing aliases. The reconciliation instead recognizes bounded model identities before legacy family aliases. This avoids changing the legacy alias table and prevents the new Fable 5.1 rule from matching Fable 5.10. Native rates are preserved from the production edits, not asserted here as independently verified current upstream prices.

External integration costs remain governed by [external model pricing](../../specs/external-model-pricing/spec.md). A synthetic catalog with deliberately different rates verifies that Claude request-log costs still use catalog rates rather than the native table.

## Regression evidence

A mocked `/v1/chat/completions` request for `cp_claude-fable-5-1`, dotted `claude-fable-5.1`, or `claude-fable-5-1-thinking-max` forwarded the wrong `claude-fable-5` model on the main baseline. The reconciled path preserves the intended wire version, suffix effort and output bounds, while plain Fable 5 is unchanged. Unit tests cover native tiers, the 272,000-token boundary, identity spellings, and nonmatching neighboring versions.

## Delivery constraint

Production edits are preserved privately outside the deployment directory. Production must remain protected by the existing dirty-source guard until the reconciled behavior is landed and source reconciliation can be proven contained in the merged result. Deployment and live model testing are not performed by these tests.
