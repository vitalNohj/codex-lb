## 1. Reproduction

- [x] 1.1 Replay Unlid's `/models` listing through a local proxy and confirm normal and streamed request logs have no cost and settle as `not_token_priced`.

## 2. Pricing support

- [x] 2.1 Read Unlid's namespaced USD-per-million input/output rates alongside the existing OpenRouter per-token format.
- [x] 2.2 Keep runtime reference pricing and serving-catalog pricing in sync, classifying malformed rates as unparseable.

## 3. Verification and documentation

- [x] 3.1 Re-run local end-to-end normal and streamed requests with a fresh store; assert the calculated cost and provenance.
- [x] 3.2 Confirm the explicit refresh upgrades a record settled by the old reader.
- [x] 3.3 Cover pricing formats, precedence, malformed/absent/zero rates, and request logging with deterministic tests.
- [x] 3.4 Document supported formats, calculated-cost semantics, and the upgrade refresh.
- [x] 3.5 Run format, lint, type, architecture, and relevant test gates; validate OpenSpec change. Focused checks pass (351 relevant tests). Whole-repo typecheck has 651 existing diagnostics; the 7,799-pass unit run has a pre-existing Settings ratchet failure (186 fields against 131). Whole-repo format check flags 7 untouched merged Alembic revisions, which this change must not edit.
