# AGENTS

## Environment

- Python: .venv/bin/python (uv, CPython 3.13.3)
- GitHub auth for git/API is available via env vars: `GITHUB_USER`, `GITHUB_TOKEN` (PAT). Do not hardcode or commit tokens.
- For authenticated git over HTTPS in automation, use: `https://x-access-token:${GITHUB_TOKEN}@github.com/<owner>/<repo>.git`

## Code Conventions

The `/project-conventions` skill is auto-activated on code edits (PreToolUse guard).

| Convention | Location | When |
|-----------|----------|------|
| Code Conventions (Full) | `/project-conventions` skill | On code edit (auto-enforced) |
| Git Workflow | `.agents/conventions/git-workflow.md` | Commit / PR |

## Workflow (OpenSpec-first)

This repo uses **OpenSpec as the primary workflow and SSOT** for change-driven development.

### How to work (default)

1) Find the relevant spec(s) in `openspec/specs/**` and treat them as source-of-truth.
2) If the work changes behavior, requirements, contracts, or schema: create an OpenSpec change in `openspec/changes/**` first (proposal -> tasks).
3) Implement the tasks; keep code + specs in sync (update `spec.md` as needed).
4) Validate specs locally: `openspec validate --specs`
5) When done: verify + archive the change (do not archive unverified changes).

### Source of Truth

- **Specs/Design/Tasks (SSOT)**: `openspec/`
  - Active changes: `openspec/changes/<change>/`
  - Main specs: `openspec/specs/<capability>/spec.md`
  - Archived changes: `openspec/changes/archive/YYYY-MM-DD-<change>/`

## Documentation & Release Notes

- **Do not add/update feature or behavior documentation under `docs/`**. Use OpenSpec context docs under `openspec/specs/<capability>/context.md` (or change-level context under `openspec/changes/<change>/context.md`) as the SSOT.
- **Do not edit `CHANGELOG.md` directly.** Leave changelog updates to the release process; record change notes in OpenSpec artifacts instead.

### Documentation Model (Spec + Context)

- `spec.md` is the **normative SSOT** and should contain only testable requirements.
- Use `openspec/specs/<capability>/context.md` for **free-form context** (purpose, rationale, examples, ops notes).
- If context grows, split into `overview.md`, `rationale.md`, `examples.md`, or `ops.md` within the same capability folder.
- Change-level notes live in `openspec/changes/<change>/context.md` or `notes.md`, then **sync stable context** back into the main context docs.

Prompting cue (use when writing docs):
"Keep `spec.md` strictly for requirements. Add/update `context.md` with purpose, decisions, constraints, failure modes, and at least one concrete example."

### Commands (recommended)

- Start a change: `/opsx:new <kebab-case>`
- Create artifacts (step): `/opsx:continue <change>`
- Create artifacts (fast): `/opsx:ff <change>`
- Implement tasks: `/opsx:apply <change>`
- Verify before archive: `/opsx:verify <change>`
- Sync delta specs → main specs: `/opsx:sync <change>`
- Archive: `/opsx:archive <change>`

## Contributing & Merge Gates

When authoring or merging a PR (as a human contributor, a collaborator,
or an AI assistant acting on behalf of either), the binding workflow is
in [`.github/CONTRIBUTING.md`](.github/CONTRIBUTING.md). The sections
an AI assistant most often needs are:

- [Merge gates](.github/CONTRIBUTING.md#merge-gates) — CI green +
  `@codex review` clean (or findings addressed) + `mergeable=CLEAN` +
  OpenSpec change folder for behavior changes + `Fixes #N` /
  `Closes #N` for issue cover.
- [Collaborator rules](.github/CONTRIBUTING.md#collaborator-rules) —
  no self-merge by default; large PRs get split (≈1-concern per PR,
  ~800 net lines / scoped capability ceiling).
- [Bus factor escape hatch](.github/CONTRIBUTING.md#bus-factor-escape-hatch)
  — self-merge allowed after **14 days** with all gates met and a
  comment invoking the clause.

An assistant preparing a merge MUST verify the gates against the
actual GitHub state (status check rollup, codex review submissions,
`mergeable` field) rather than asserting them from local history.
Local `uv run pytest` / `uv run ruff` / `codex review --base origin/main`
are encouraged but not substitutes for the cloud gates.

## PR Readiness / Review Trapdoors

These rules encode recurring review blockers observed across codex-lb PRs.

- OpenSpec is a hard gate for behavior, API, schema, CLI,
  dashboard-visible, proxy-routing, operator-contract, and compatibility
  changes. Create or update `openspec/changes/<slug>/` before coding, keep
  `spec.md` normative with MUST/SHALL-style requirements, put rationale and
  examples in `context.md` or change notes, and run strict OpenSpec validation
  before calling the PR ready. Code/tests alone are not enough when OpenSpec is
  required.
- Codex review state must come from current-head GitHub evidence. Check labels,
  latest Codex review/comment/reaction, and GraphQL review threads before using
  or claiming `🤖 codex: ok`. Usage-limit, environment, or missing-review
  results mean missing evidence, not approval. Unresolved non-outdated P-level
  Codex threads block readiness even when a top-level review comment looks
  clean.
- Proxy failover and retry patches must prove account ownership and settlement
  invariants. File-pinned requests must not cross accounts; API-key reservations
  must settle before error-health writes; excluded accounts must actually leave
  the selection loop; idle disconnects must not mark otherwise healthy accounts
  unhealthy; security/trusted-access routing must degrade only along the
  documented path.
- Async, fan-out, and session-lifecycle patches must prove task ownership and
  cleanup. Do not share one `AsyncSession` across concurrent tasks; cancel or
  await spawned tasks on failure; preserve finalization/settlement paths after
  partial errors; bound fan-out; and test partial-failure behavior, not only
  the all-success path.
- Database migrations must prove Alembic graph and data hygiene. New revisions
  must sit on the current intended parent with a single-head upgrade path, have
  downgrade/upgrade coverage where the project expects it, and include
  historical-row backfills or compatibility handling when new fields affect
  existing data.
- Issue-resolving PRs must name the exact `Fixes #N` / `Closes #N`, or state
  that they are partial. Keep PRs one concern wide. Revive stale work by making
  a focused branch on current `main`; do not drag an old broad/conflicted branch
  forward unless the maintainer explicitly wants that shape.
- Bug fixes need regression coverage at the externally failing product path:
  route, bridge, websocket, CLI, schema, dashboard UI, or migration path as
  applicable. Helper-only tests are not enough when the failing surface is
  elsewhere.
- Compatibility work must verify canonical and equivalent paths, trailing slash
  behavior, external error envelopes, env-var semantics, and response-schema
  contracts. Update OpenSpec/context and tests together so docs cannot promise
  behavior the code does not implement.

## Learned User Preferences

- Prefer replacing visible "sidecar" labels with provider-specific text: "CLIProxyAPI Integration", "OpenRouter Integration", "OmniRoute Integration".
- Dashboard account cards and Accounts-tab integration items should be clean: remove health/quota/models/requests rows from the Claude card, model-count rows from OpenRouter/OmniRoute cards, and all duplicate sidecar-type/provider-name badges (the heading already names the provider).
- Request Logs table should display sidecar rows like normal rows: no sidecar badge under Model, no "Sidecar HTTP" in Transport (just "HTTP"), and the Account column shows provider names without "sidecar" ("CLIProxyAPI: <email>", "OpenRouter", "OmniRoute").
- Settings UI sidecar sections should place the enable toggle above the explanation callout, not below it.
- OpenRouter/OmniRoute settings should keep Discovered Models collapsible inside the integration card, above Save/Clear/API key actions; OpenRouter places it under Model prefixes, and OmniRoute replaces the selected-model row under manual add.
- Move integration controls from Settings into the relevant Accounts tab item (e.g. CLIProxyAPI quota estimation and a manual "Test connection" button); Settings should run test-connection automatically on save.
- When investigating behavior issues, prioritize querying the database and request logs over code analysis to avoid making dangerous assumptions about the current state.
- External navigation links (e.g. "Open OmniRoute") in the dashboard or settings cards should always open in a new browser tab with `rel="noopener noreferrer"`.
- Do not implement a plan (especially an old/handed-off plan) before confirming the work is actually necessary; verify each claimed gap against real request logs/DB/traffic and stop/revert if it is already handled or never exercised.
- Do not overbuild simple asks: when the user wants a quick fix to current state (e.g. a misdetected account plan), make the minimal manual DB correction rather than adding new endpoints, UI, OpenSpec changes, and tests. A pile of changes for a "simple thing" is a strong negative signal; prefer the smallest path and ask before scaling scope.
- Sidecar/External integration settings should autosave on explicit user actions (add/remove prefix, add/remove full model, toggle strip, Add API key) instead of having Save/Clear buttons; an "Add API key" action overwrites the existing key, and Base URL/numeric fields persist on blur or Enter.
- Combine the CLIProxyAPI/OpenRouter/OmniRoute (and planned Ollama) settings cards into one "External Integrations" card with a tab per integration; keep each integration's own provider/state and render them frameless inside the tabs (shared `Frame` gains an opt-in `bare` prop).

## Learned Workspace Facts

- codex-lb runs as a systemd user service (`systemctl --user restart codex-lb.service`). Backend code changes require a service restart to take effect, but do not restart the service (or rerun the full test suite) unprompted: the shared instance serves multiple concurrent agents and a restart can break their in-flight work. Restart only when the user has confirmed it is safe. Frontend build artifacts live in `app/static/` and are served by the FastAPI backend in production mode; the `/codex` API prefix is stripped by the reverse proxy (HTTPS on port 443).
- Standard validation commands: `openspec validate --specs` for all specs; `openspec validate <change> --strict` for a specific change. OpenSpec validation requires at least one delta spec in the change folder for any behavior change, even a small UI refinement; UI-only changes (layout, copy, visibility) can skip spec deltas only when following an established precedent (e.g. OpenRouter settings refine declared no spec deltas). `--strict` parses only the FIRST LINE of a requirement body for MUST/SHALL, so put a MUST/SHALL on the requirement's first sentence/line; debug parsed deltas with `openspec change show <change> --json --deltas-only`.
- Testing commands: `uv run pytest <path>` for backend; `npx vitest run <path>` for frontend. Frontend Vitest must be run from the `frontend/` directory (not repo root) so the project's Vite alias config resolves; running it from root fails.
- The Cursor↔OpenAI compatibility layer must stay aligned with upstream codex-lb; CLIProxyAPI already converts to OpenAI chat format, so only add minimal Claude-specific handling and avoid divergence (custom Cursor-specific hardening was removed — confirm a gap is real in current traffic before re-adding). Codex control endpoints (e.g. `trace_summarize`) must be raw pass-through to the backend; do not inject `reasoning`/`service_tier` or rewrite the model on control payloads, since that broke Cursor `/summarize` compaction (only triggered with the OpenAI API key enabled, not on Composer models).
- At the context limit, return an error Cursor recognizes as a compaction trigger; surfacing it as an API-key/rate-limit error prevents Cursor from compacting. Note this proxy-side auto-compact (error matching on chat-completions responses) is separate from Cursor IDE's manual `/summarize` button, which bypasses custom OpenAI-compatible providers/proxy base URL and connects directly to Cursor's internal infra (api2.cursor.sh); the `/backend-api/codex/memories/trace_summarize` endpoint serves the Codex CLI's memory consolidation pipeline, not Cursor's summarize button.
- The CLIProxyAPI management secret must be configured as plaintext in the database (which the app then encrypts) because the sidecar hashes the config value on its end.
- Claude sidecar usage estimates prefer authoritative OAuth-reported percentages over local token-budget math when a pro/team plan is configured. Sidecar cost capture mirrors OpenRouter for OmniRoute: free-model detection uses a marker regex (e.g. `:free`) for OpenRouter, but OmniRoute has opaque free models (e.g. `oc/big-pickle`) with no textual marker, so a curated `_OPAQUE_FREE_MODELS` allowlist in `app/core/usage/pricing.py` is required; genuinely paid models with no pricing entry must stay `NULL` (not zero), and historical rows are repaired via a backfill migration.
- Sidecar routing uses one shared resolver (`app/modules/proxy/sidecar_routing.py`) for both chat-completions and Responses paths: full-model exact match (case-insensitive) beats any prefix globally and is forwarded as-is (never stripped); otherwise longest-prefix match wins with a per-prefix `strip` flag and deterministic provider tie-break. Prefixes/full models are stored as structured objects (`{prefix, strip}` and `full_models`), must be globally unique across CLIProxyAPI/OpenRouter/OmniRoute (only allowed overlap: a prefix vs. a full model, where the full model wins), and CLIProxyAPI's `cp-`/`cp_` are seeded default editable strip-on rows, not hardcoded aliases. Dispatch splits effective vs wire model: forwarded payloads use the resolver's stripped `wire_model`, while request logs and quota reservation finalization use the un-stripped `effective_model` (the resolver strips in `api.py`, so dispatch builders receive an already-resolved wire model).
- DeepSeek V4 thinking-mode tool calls fail in Cursor (400 "reasoning_content in the thinking mode must be passed back") because DeepSeek requires prior assistant `reasoning_content` echoed back with tool-call history and Cursor does not. The fix is server-side only (codex-lb forcibly re-injects cached reasoning into the outgoing assistant tool-call message; Cursor never cooperates) and lives in `app/modules/proxy/deepseek_v4_compat.py`, hooked into ALL THREE sidecar chat-completions dispatch paths — OmniRoute (primary, opencode), OpenRouter, and CLIProxyAPI/Claude (DeepSeek can route there via a `cp-deepseek-v4-*` strip-prefix full model) — not just OpenRouter/OmniRoute and not native Codex. Cache key = SHA-256 of canonical conversation prefix (roles/content/tool_calls, excluding `reasoning_content`) + provider + model family + api-key hash, so byte-identical Cursor-replayed histories produce matching keys; isolate by provider/family/api-key. Multi-round conversations require re-injecting EVERY prior assistant tool-call turn, not just the latest. On the Claude path, capture reasoning from the RAW upstream chunks/response BEFORE tool-call-name rewriting (the path renames tool calls to client-facing names), else keys won't match re-injection. Reference behavior: `yxlao/deepseek-cursor-proxy`.
- Alembic autogenerate on SQLite reports a false-positive `modify_default` server-default drift (e.g. on `dashboard_settings.*_json` columns); this must be explicitly ignored in the central DB migration helper rather than treated as a migration-readiness failure. There is no root `alembic.ini`; use the repo's Python/uv migration entry points (not bare `alembic heads`) for head/schema checks.
- The app database is SQLite at `~/.codex-lb/store.db`. Account plan lives in `accounts.plan_type` (`free`/`plus`/etc.); stale "Monthly" usage bars come from `usage_history` rows with `window = 'monthly'`. To correct a misdetected Plus-as-free account without logout/OAuth refresh: `UPDATE accounts SET plan_type='plus'` for that id and delete its `usage_history` rows where `window='monthly'`. Forcing an OAuth token refresh ("re-sync") to fix this is the wrong approach — it contacts the OAuth refresh endpoint and can mark the account as needing re-auth. Note `request_logs` has no raw URL/path/endpoint column and the `RequestKind` enum has only `normal`/`warmup` (no `compact`/`summarize`), so identify summarize/compact traffic by timing + `useragent` + `model` + `error_code`, not by path.
- OmniRoute runs as a systemd user service (`omniroute.service`) listening on `:20128`, started from the bun-global install (`~/.bun/bin/omniroute` → `~/.bun/install/global/...`), NOT the npm-global (`~/.npm-global`) location. Update outside the in-UI updater with `bun add -g omniroute@<version> && systemctl --user restart omniroute.service`. Real runtime config (incl. `STORAGE_ENCRYPTION_KEY` that decrypts stored provider creds) lives in `~/.omniroute/.env` (loaded via systemd `EnvironmentFile`); the package-dir `.env` generated by `postinstall`/`sync-env` does not override it. OmniRoute uses Node's built-in `node:sqlite`, so no native module rebuild is required (the postinstall native-copy step no-ops).
