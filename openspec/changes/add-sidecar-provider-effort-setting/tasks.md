## 1. Backend persistence and settings API

- [ ] 1.1 Add four nullable `String` columns to `DashboardSettings` and a new Alembic revision (`upgrade`/`downgrade`).
- [ ] 1.2 Add the four fields to `DashboardSettingsResponse` and `DashboardSettingsUpdateRequest` with a shared validator accepting `none|minimal|low|medium|high|xhigh` or null, normalizing blanks to null and values to lowercase.
- [ ] 1.3 Thread the fields through `SettingsService` (`DashboardSettingsData`, `DashboardSettingsUpdateData`, `_to_data`, `update_settings`) and `SettingsRepository.update()` using the `_UNSET` sentinel so explicit null clears the stored value.
- [ ] 1.4 Add the fields to `_dashboard_settings_response()`.
- [ ] 1.5 Add settings tests: default null, accepts `xhigh`, lowercases mixed case, rejects invalid, and set-then-clear via null.

## 2. Sidecar dispatch injection

- [ ] 2.1 Add `default_reasoning_effort: str | None = None` to the four sidecar config dataclasses and populate them from settings.
- [ ] 2.2 Add a reusable `set_reasoning_effort_if_absent(body, effort)` helper preserving "client effort wins".
- [ ] 2.3 Inject the provider default in Claude (after suffix profile), OpenRouter, and OmniRoute builders.
- [ ] 2.4 Inject the Ollama default through the `think` field only when thinking is not already enabled; update callers.
- [ ] 2.5 Add per-provider tests proving default injection, explicit-effort preservation, Claude suffix precedence, and Ollama `think` mapping.

## 3. Settings UI dropdown

- [ ] 3.1 Add the effort enum and four fields to frontend schemas and `buildSettingsUpdateRequest`.
- [ ] 3.2 Extend the shared sidecar integration card state/actions and add a reusable effort `<Select>` subcomponent.
- [ ] 3.3 Render the dropdown in all four provider settings cards and wire it through each `buildPatch`.
- [ ] 3.4 Add Settings tests for selecting `Extra high` (saves `xhigh`) and `Default` (saves null).

## 4. Accounts and Dashboard card dropdowns

- [ ] 4.1 Load settings in the Accounts and Dashboard pages and pass settings + save callback to synthetic cards.
- [ ] 4.2 Render the shared effort dropdown in the synthetic account detail card and the Dashboard synthetic account card.
- [ ] 4.3 Fix Ollama provider detection/labels in synthetic detail/dashboard cards.
- [ ] 4.4 Add Accounts and Dashboard card tests proving the dropdown renders and saves the same `/api/settings` field.

## 5. Validation

- [ ] 5.1 Run `openspec validate add-sidecar-provider-effort-setting --strict` and `openspec validate --specs`.
- [ ] 5.2 Run `uv run codex-lb-db upgrade head` and `uv run codex-lb-db check`.
- [ ] 5.3 Run the targeted backend and frontend tests, plus `uv run ruff check` and `uv run ty check`.
