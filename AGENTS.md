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
- Dashboard account cards should show a cleaner interface: remove health/quota/models/requests metadata rows from the Claude card; remove model-count rows from OpenRouter/OmniRoute cards; remove duplicate sidecar-type badges.
- Request Logs table should display sidecar rows like normal rows: no sidecar badge under Model, no "Sidecar HTTP" in Transport (just "HTTP").
- Account column in Request Logs should show provider names without "sidecar": "CLIProxyAPI: <email>", "OpenRouter", "OmniRoute".
- Settings UI sidecar sections should place the enable toggle above the explanation callout, not below it.
- Accounts tab integration items (CLIProxyAPI, OpenRouter, OmniRoute) should not show provider-name badges; the heading already names the provider.
- Move integration controls from Settings into the relevant Accounts tab item (e.g. CLIProxyAPI quota estimation and a manual "Test connection" button); Settings should run test-connection automatically on save.
- When investigating behavior issues, prioritize querying the database and request logs over code analysis to avoid making dangerous assumptions about the current state.
- External navigation links (e.g. "Open OmniRoute") in the dashboard or settings cards should always open in a new browser tab with `rel="noopener noreferrer"`.

## Learned Workspace Facts

- codex-lb runs as a systemd user service (`systemctl --user restart codex-lb.service`). Backend code changes require a service restart to take effect.
- Frontend build artifacts live in `app/static/` and are served by the FastAPI backend in production mode. The `/codex` API prefix is stripped by the reverse proxy (HTTPS on port 443).
- Standard validation commands: `openspec validate --specs` for all specs; `openspec validate <change> --strict` for a specific change.
- Testing commands: `uv run pytest <path>` for backend; `npx vitest run <path>` for frontend.
- UI-only changes (layout, copy, visibility) can skip OpenSpec spec deltas when following an established precedent (e.g. OpenRouter settings refine declared no spec deltas).
- The Cursor↔OpenAI compatibility layer must stay aligned with upstream codex-lb; CLIProxyAPI already converts to OpenAI chat format, so only add minimal Claude-specific handling and avoid divergence from upstream behavior.
- Codex control endpoints (e.g. `trace_summarize`) must be raw pass-through to the backend; do not inject `reasoning`/`service_tier` or rewrite the model on control payloads. Such policy rewriting broke Cursor `/summarize` compaction (only triggered with the OpenAI API key enabled, not on Composer models).
- At the context limit, return an error Cursor recognizes as a compaction trigger; surfacing it as an API-key/rate-limit error prevents Cursor from compacting.
- OpenSpec validation requires at least one delta spec in the change folder for any behavior change, even if the change is a small UI refinement.
- OmniRoute model routing uses an exact case-insensitive string match; models must be explicitly added to the "selected models" list to avoid falling through to the default OpenAI path.
- The CLIProxyAPI management secret must be configured as plaintext in the database (which the app then encrypts) because the sidecar hashes the config value on its end.
- Claude sidecar usage estimates prefer authoritative OAuth-reported percentages over local token-budget math when a pro/team plan is configured.
