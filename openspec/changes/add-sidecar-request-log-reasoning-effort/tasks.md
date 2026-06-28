## 1. Database and request-log model

- [ ] 1.1 Add nullable `requested_reasoning_effort` to `RequestLog` in `app/db/models.py`, adjacent to `reasoning_effort`.
- [ ] 1.2 Add a new single-head Alembic revision that adds/drops `request_logs.requested_reasoning_effort` with no historical backfill.
- [ ] 1.3 Add `requested_reasoning_effort` to `RequestLogsRepository.add_log()` and persist it on new rows.

## 2. Sidecar requested/effective capture

- [ ] 2.1 Add a shared `read_reasoning_effort(body)` helper in `sidecar_model_profiles.py` reading top-level `reasoning_effort` or nested `reasoning.effort`.
- [ ] 2.2 In each sidecar builder (`build_sidecar_chat_payload`, `build_openrouter_chat_payload`, `build_omniroute_chat_payload`, `build_ollama_chat_payload`) capture requested (pre-override) and effective (post-override) effort and expose both via the payload dataclasses.
- [ ] 2.3 Thread both efforts into every `repo.add_log(...)` call in the four sidecar dispatch log writers (Claude stream + non-stream, OpenRouter, OmniRoute, Ollama).

## 3. Request-log API and dashboard UI

- [ ] 3.1 Add `requested_reasoning_effort` to `RequestLogEntry` and map it from `RequestLog`.
- [ ] 3.2 Add `requestedReasoningEffort` to the frontend request-log schema and mock factory.
- [ ] 3.3 Render the requested effort next to the model in the recent-requests table (and detail drawer) only when it is non-null and differs from the effective `reasoningEffort`.

## 4. Tests

- [ ] 4.1 Add per-provider builder tests proving requested-vs-effective capture for override, no-override, omitted-effort, and override-injected cases.
- [ ] 4.2 Update the affected sidecar dispatch log tests for the new `add_log` fields.
- [ ] 4.3 Add a frontend table test proving differing requested/effective effort renders the requested annotation and matching/null does not.

## 5. Validation

- [ ] 5.1 Run `openspec validate add-sidecar-request-log-reasoning-effort --strict` and `openspec validate --specs`.
- [ ] 5.2 Run `uv run codex-lb-db upgrade head` and `uv run codex-lb-db check`.
- [ ] 5.3 Run targeted sidecar dispatch + frontend tests, plus ruff on touched files.
