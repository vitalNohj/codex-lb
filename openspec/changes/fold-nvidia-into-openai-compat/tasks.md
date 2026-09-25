## 1. OpenSpec

- [x] 1.1 Proposal, design, tasks, delta spec.
- [x] 1.2 `openspec validate fold-nvidia-into-openai-compat --strict`.

## 2. Migration

- [x] 2.1 Fold-and-drop migration on the current head; upgrade and downgrade.
- [x] 2.2 Test: configured NVIDIA folds into one entry with the key preserved; unconfigured NVIDIA folds nothing; downgrade re-adds columns.

## 3. Backend removal

- [x] 3.1 Delete `app/modules/nvidia_sidecar/`, `app/modules/proxy/nvidia_sidecar_dispatch.py`, `app/core/clients/nvidia_sidecar.py`, `app/modules/accounts/nvidia_sidecar_summary.py`.
- [x] 3.2 Remove `nvidia` branches from `proxy/api.py`, `dashboard/api.py`, `dashboard/service.py`, `accounts/service.py`, `settings/*`, `external_pricing_sources.py`, `external_pricing/providers.py`, `sidecar_routing.py`, `db/models.py`, `config/settings.py`, `dependencies.py`, `main.py`.
- [x] 3.3 Delete NVIDIA tests; update tests asserting provider order or settings payloads.

## 4. Frontend removal

- [x] 4.1 Delete `nvidia-sidecar-settings.tsx` and its test.
- [x] 4.2 Remove `nvidia` from settings schema/payload/api/hooks, integrations card, account card/list/detail/actions, filter toggle, request table, prefs store, MSW handlers, fixtures.
- [x] 4.3 Typecheck, lint, tests, build.

## 5. Verification

- [x] 5.1 Run the migration against a copy of the live DB; confirm an `NVIDIA` entry with the decryptable key.
