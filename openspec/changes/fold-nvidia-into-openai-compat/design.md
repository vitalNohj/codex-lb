## Overview

Delete the NVIDIA clone and let the generic OpenAI-compat endpoint list carry it. The only user-visible artefact after migration is an `NVIDIA` endpoint entry with the previously stored URL and key.

## Migration

Revision `20260925_000000_fold_nvidia_into_openai_compat`, parent `20260923_010000_merge_gpt_6_sol_luna_and_opus_5_5_heads` (current single head).

Upgrade:

1. Read the `nvidia_sidecar_*` columns from `dashboard_settings` (id = 1). If the columns are absent, do nothing.
2. If NVIDIA was configured (`nvidia_sidecar_api_key_encrypted IS NOT NULL` OR `nvidia_sidecar_enabled` OR non-default base URL OR any prefixes/full models), append one entry to `openai_compat_endpoints_json`:
   - `id`: new UUID4
   - `name`: `NVIDIA` (suffix ` (2)`, ` (3)` ... if the name is already taken, case-insensitive)
   - `enabled`, `base_url`, `model_prefixes`, `full_models`, `connect_timeout_seconds`, `request_timeout_seconds`, `models_cache_ttl_seconds`, `default_reasoning_effort`: copied verbatim
   - `api_key_encrypted`: the raw Fernet bytes base64-encoded (the OpenAI-compat list stores `base64(fernet_bytes)`; the NVIDIA column stores `fernet_bytes`; same `TokenEncryptor`, so no re-encryption)
   - health fields: `null`
   - Skip the append if the list already holds 32 entries (log a warning; the operator can re-add by hand).
3. Rewrite `request_logs.source` from `nvidia_sidecar` to `openai_compat:<new id>` when an entry was created, else leave rows untouched.
4. Drop the thirteen `nvidia_sidecar_*` columns.

Downgrade: re-add the columns with their original defaults (empty). The folded entry stays in the JSON list; no data is lost, it is just no longer surfaced on a NVIDIA tab.

## Routing order

`SIDECAR_PROVIDER_ORDER` drops `"nvidia"`. The folded endpoint ranks last with every other generic endpoint. Prefix/full-model uniqueness already forbids overlap, so the tie-break slot has no observable effect.

## Env

`CODEX_LB_NVIDIA_SIDECAR_*` settings are removed from `app/core/config/settings.py`. They only seeded fresh-install prefixes (default empty).
