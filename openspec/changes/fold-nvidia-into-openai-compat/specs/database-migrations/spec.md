## ADDED Requirements

### Requirement: Fold NVIDIA settings into the OpenAI-compat endpoint list

Alembic MUST fold any configured NVIDIA sidecar settings into one `openai_compat_endpoints_json` entry and then drop every `dashboard_settings.nvidia_sidecar_*` column. The revision MUST parent the live Alembic head. Upgrade MUST be idempotent: when the NVIDIA columns are absent it MUST do nothing.

A NVIDIA configuration counts as configured when an encrypted API key is stored, or the integration is enabled, or the base URL differs from `https://integrate.api.nvidia.com/v1`, or any prefix or full model is stored. The folded entry MUST be named `NVIDIA` (suffixed ` (n)` when that name is already taken, case-insensitively) and MUST carry the base URL, enabled flag, prefixes, full models, timeouts, cache TTL, reasoning-effort override, and the API key ciphertext re-encoded as base64 without re-encryption. Health fields MUST be null. When the list already holds the maximum number of endpoints the migration MUST skip the append and still drop the columns.

When an entry is created, `request_logs.source` rows equal to `nvidia_sidecar` MUST be rewritten to the new entry's provider id.

Downgrade MUST re-add the NVIDIA columns with their original server defaults and MUST leave the folded entry in place.

#### Scenario: Configured NVIDIA folds into one entry

- **GIVEN** `dashboard_settings` holds a NVIDIA API key ciphertext and base URL
- **WHEN** the migration upgrades
- **THEN** `openai_compat_endpoints_json` gains an entry named `NVIDIA` with that base URL
- **AND** the entry's `api_key_encrypted` decodes to the original ciphertext
- **AND** the `nvidia_sidecar_*` columns are gone

#### Scenario: Unconfigured NVIDIA folds nothing

- **GIVEN** the NVIDIA columns hold only their defaults
- **WHEN** the migration upgrades
- **THEN** `openai_compat_endpoints_json` is unchanged
- **AND** the `nvidia_sidecar_*` columns are gone

#### Scenario: Upgrade on a database without the NVIDIA columns

- **GIVEN** `dashboard_settings` has no `nvidia_sidecar_*` columns
- **WHEN** the migration upgrades
- **THEN** nothing changes

#### Scenario: Downgrade restores the columns

- **GIVEN** the migration has been applied
- **WHEN** it downgrades
- **THEN** the `nvidia_sidecar_*` columns exist with their original defaults
- **AND** the folded `NVIDIA` entry remains in `openai_compat_endpoints_json`
