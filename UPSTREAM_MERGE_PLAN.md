# Align Fork With Upstream `main` (1.20.1) — Execution Plan

**Goal (one sentence):** Merge `upstream/main` (Soju06, release 1.20.1) into our fork's `main` without losing any of our custom functionality (sidecars, DeepSeek V4 compat, pricing/cost tracking).

**Not in this plan:** Pushing to `origin`, opening a PR, restarting the `codex-lb` systemd service, or deleting old branches. Those are separate, post-merge actions.

## Facts established (verified, not assumed)

- Merge base: `41e6fffc` (2026-06-09). Upstream HEAD: `17c1762d` (1.20.1). Our HEAD: `90fac529`.
- Upstream is **38 commits** ahead of the base; our fork is **91 commits** ahead.
- We already cherry-picked upstream **PR #977** (`bridge codex compaction triggers`) and **PR #950** (`normalize responses instruction messages`) — expect these to dedup cleanly.
- `git merge-tree` preview shows **18 conflicting files** (full list in Phase 3). Everything else auto-merges.
- Both sides added Alembic migrations → there will be **two alembic heads** after merge that MUST be joined with a merge revision. Both sides happen to have a file named `20260611_000000_*` but with **different revision IDs**, so no filename clash in git, but heads must be reconciled.
- Our sidecar HTTP clients do **not** import `curl_cffi`; only the 3 core upstream clients (`codex.py`, `proxy.py`, `proxy_websocket.py`) do, and upstream's big refactor (PR #940) rewrites exactly those. Low risk to our code, but core client tests will change.
- Working tree is currently **clean** (the startup git-status snapshot was stale).

## Conflict files, grouped by effort (from `git merge-tree` + churn analysis)

**Group A — trivial / mechanical (union or pick-newer):**
- `.all-contributorsrc` — union the contributor lists.
- `pyproject.toml` — take upstream version/dep bumps; keep any of our added deps.
- `uv.lock` — do NOT hand-merge; regenerate with `uv lock` after `pyproject.toml` is settled.

**Group B — ours-dominant (huge custom additions, tiny upstream touch):**
- `app/modules/settings/schemas.py` (ours +387 / up +3)
- `app/modules/settings/service.py` (ours +569 / up +8)
- `app/modules/settings/repository.py` (ours +260 / up +5)
- `app/modules/settings/api.py` (ours +344 / up +19)
- `frontend/src/features/settings/schemas.ts` (ours +377 / up +8)
- `frontend/src/features/settings/payload.ts` (ours +34 / up +1)
- `frontend/src/features/dashboard/components/account-card.tsx` (ours +156 / up +6)
  - Strategy: keep our structure, re-apply the small upstream hunk on top.

**Group C — upstream-dominant (large upstream rewrite, small our touch):**
- `app/modules/proxy/request_policy.py` (up +29 / ours +47) — both real; merge by hand.
- `app/modules/proxy/api.py` (up +173 / ours +516) — **highest risk**; both heavily changed. Hand-merge carefully.
- `frontend/src/features/accounts/components/account-detail.tsx` (up +147 / ours +8) — take upstream, re-apply our small bit.
- `frontend/src/features/dashboard/components/dashboard-page.tsx` (up +29 / ours +5)
- `frontend/src/components/layout/app-header.tsx` (up +30 / ours +22) — our OmniRoute link vs upstream header changes.

**Group D — test/mocks (reconcile both sets of cases):**
- `frontend/src/features/settings/components/import-settings.test.tsx`
- `frontend/src/features/dashboard/components/account-card.test.tsx`
- `frontend/src/test/mocks/factories.ts`

## Before you start

- [ ] Step 0.1: Run `git status` and confirm output is empty (clean tree). If not, stop and commit or stash first.
- [ ] Step 0.2: Run `git fetch upstream --tags` and confirm it completes without error.
- [ ] Step 0.3: Record current head for rollback: run `git rev-parse HEAD` and paste the hash into a scratch note (it should be `90fac529...`).
- [ ] Step 0.4: Create a safety branch pointer: `git branch backup/pre-upstream-merge`. Confirm with `git branch --list 'backup/*'`.
- [ ] Step 0.5: Create the working branch: `git switch -c merge/upstream-1.20.1`. Confirm with `git branch --show-current`.

## Phase 1: Baseline green before touching anything

**What this phase achieves:** Proves the fork is healthy before the merge, so any later failure is attributable to the merge, not pre-existing breakage.

- [ ] Step 1.1: Run backend tests: `uv run pytest -q`. Confirm it passes (or note the exact pre-existing failures in your scratch note).
- [ ] Step 1.2: Run frontend tests from the `frontend/` dir: `cd frontend && npx vitest run`. Confirm pass; note pre-existing failures.
- [ ] Step 1.3: Run `openspec validate --specs` and confirm no errors.
- [ ] Step 1.4: Capture the current Alembic head list: `uv run python -m app.db.migrate heads` (or the repo's documented head command). Save the output — you'll compare after merge.

**Phase 1 done when:** You have a written record of baseline test + migration-head state.

## Phase 2: Start the merge (no conflict resolution yet)

**What this phase achieves:** Kicks off the merge so git marks the exact conflicts; we resolve them in controlled order.

- [ ] Step 2.1: Run `git merge --no-commit --no-ff upstream/main`. Expect it to stop with conflicts. Do NOT commit yet.
- [ ] Step 2.2: Run `git status` and confirm the "Unmerged paths" list matches the 18 files in the plan. If a NEW file appears that's not listed, stop and investigate before continuing.
- [ ] Step 2.3: Run `git diff --name-only --diff-filter=U` and save the conflict list to your scratch note.

**Phase 2 done when:** Merge is in progress and the conflict set matches expectations.

## Phase 3: Resolve conflicts in difficulty order (easy first)

**What this phase achieves:** Resolves all 18 conflicts, building confidence on easy files before the hard ones.

### Group A — trivial
- [ ] Step 3.1: Open `.all-contributorsrc`. Keep BOTH contributor lists (union the `contributors` array, drop duplicate logins). Save. Run `git add .all-contributorsrc`.
- [ ] Step 3.2: Open `pyproject.toml`. Take upstream's version string and dependency bumps; keep any dependency lines that are ours-only. Save. Run `git add pyproject.toml`.
- [ ] Step 3.3: Do NOT edit `uv.lock` by hand yet — leave it conflicted; it gets regenerated in Phase 4.

### Group B — ours-dominant (keep ours, graft small upstream hunk)
- [ ] Step 3.4: For each file in Group B, open it and locate the `<<<<<<<`/`>>>>>>>` markers.
- [ ] Step 3.5: `app/modules/settings/schemas.py`: keep our version; read upstream's +3 lines (Step 3.5a) and re-add them if not already present.
  - [ ] Step 3.5a: Run `git diff 41e6fffc..upstream/main -- app/modules/settings/schemas.py` to see exactly what upstream added.
- [ ] Step 3.6: `app/modules/settings/service.py`: same approach — keep ours, graft upstream's +8 lines. Verify by re-reading the upstream diff for this file.
- [ ] Step 3.7: `app/modules/settings/repository.py`: keep ours, graft upstream's +5 lines.
- [ ] Step 3.8: `app/modules/settings/api.py`: keep ours, graft upstream's +19 lines (check for a new route/field upstream added).
- [ ] Step 3.9: `frontend/src/features/settings/schemas.ts`: keep ours, graft upstream's +8 lines.
- [ ] Step 3.10: `frontend/src/features/settings/payload.ts`: keep ours, graft upstream's +1 line.
- [ ] Step 3.11: `frontend/src/features/dashboard/components/account-card.tsx`: keep ours, graft upstream's +6 lines.
- [ ] Step 3.12: After each Group B file is clean of markers, run `git add <file>`.

### Group C — upstream-dominant (take upstream, re-apply our intent)
- [ ] Step 3.13: `frontend/src/features/accounts/components/account-detail.tsx`: take upstream's larger version, then re-apply our small +8 change (read `git diff 41e6fffc..HEAD -- <file>` first). `git add` when clean.
- [ ] Step 3.14: `frontend/src/features/dashboard/components/dashboard-page.tsx`: take upstream, re-apply our +5. `git add` when clean.
- [ ] Step 3.15: `frontend/src/components/layout/app-header.tsx`: take upstream header changes, re-add our OmniRoute link (must keep `target="_blank" rel="noopener noreferrer"` per our convention). `git add` when clean.
- [ ] Step 3.16: `app/modules/proxy/request_policy.py`: read BOTH diffs (upstream +29, ours +47); merge by hand so both behaviors coexist. `git add` when clean.

### Group C-critical — `app/modules/proxy/api.py` (do this slowly)
- [ ] Step 3.17: Read upstream's changes: `git diff 41e6fffc..upstream/main -- app/modules/proxy/api.py`.
- [ ] Step 3.18: Read our changes: `git diff 41e6fffc..HEAD -- app/modules/proxy/api.py`.
- [ ] Step 3.19: Resolve so BOTH survive: upstream's proxy/transport changes AND our sidecar routing dispatch + `effective_model`/`wire_model` split (the resolver strips in `api.py` per our routing design). Do not let either side delete the other's routes/handlers.
- [ ] Step 3.20: Search the resolved file for leftover markers: `grep -nE '^(<<<<<<<|=======|>>>>>>>)' app/modules/proxy/api.py` — expect no output. `git add` when clean.

### Group D — tests & mocks (keep both sets of cases)
- [ ] Step 3.21: `frontend/src/test/mocks/factories.ts`: union both sides' factory fields/handlers; no case should be dropped. `git add` when clean.
- [ ] Step 3.22: `frontend/src/features/settings/components/import-settings.test.tsx`: keep both sides' test cases. `git add`.
- [ ] Step 3.23: `frontend/src/features/dashboard/components/account-card.test.tsx`: keep both sides' assertions. `git add`.
- [ ] Step 3.24: Run `git diff --name-only --diff-filter=U` and confirm ONLY `uv.lock` remains unmerged.

**Phase 3 done when:** Every conflict except `uv.lock` is resolved and staged, with zero conflict markers left (verify: `grep -rnE '^(<<<<<<<|=======|>>>>>>>)' app/ frontend/src/ --include='*.py' --include='*.ts' --include='*.tsx'` returns nothing).

## Phase 4: Lockfile + dependency reconciliation

**What this phase achieves:** Produces a valid `uv.lock` matching the merged `pyproject.toml`.

- [ ] Step 4.1: Run `git checkout --theirs uv.lock` then `git checkout --ours uv.lock` is NOT enough — instead run `uv lock` to regenerate from the merged `pyproject.toml`.
- [ ] Step 4.2: Run `git add uv.lock`.
- [ ] Step 4.3: Run `git diff --name-only --diff-filter=U` and confirm it is now EMPTY.
- [ ] Step 4.4: If the frontend lockfile (`frontend/bun.lockb` or `package-lock.json`) conflicted at any point, regenerate it the same way (re-run the install) rather than hand-editing.

**Phase 4 done when:** No unmerged paths remain and lockfiles are regenerated, not hand-merged.

## Phase 5: Reconcile Alembic migration heads (critical)

**What this phase achieves:** Ensures a single linear upgrade path after combining both sides' migrations.

- [ ] Step 5.1: List heads with the repo's command: `uv run python -m app.db.migrate heads` (use the exact entry point the repo uses — there is no root `alembic.ini`).
- [ ] Step 5.2: If exactly ONE head: skip to Step 5.5. If TWO heads (expected — our sidecar chain + upstream guest-access chain), continue.
- [ ] Step 5.3: Create a NEW merge revision joining both heads. Use the repo's migrate tooling to autogenerate an empty merge revision whose `down_revision` is a tuple of both head IDs (our `20260619_013000_add_ollama_sidecar_dashboard_settings` and upstream's latest guest-access head).
- [ ] Step 5.4: Open the new merge revision file and confirm `down_revision` is a tuple of both head ids and `upgrade()`/`downgrade()` are empty (pure merge node).
- [ ] Step 5.5: Re-run `... migrate heads` and confirm there is now exactly ONE head.
- [ ] Step 5.6: Remember the false-positive `modify_default` SQLite drift on `dashboard_settings.*_json` is expected and already ignored centrally — do not treat it as a failure.
- [ ] Step 5.7: Apply migrations against a throwaway DB to prove the graph runs: point at a temp sqlite file and run the upgrade-to-head command. Confirm it reaches head with no error.
- [ ] Step 5.8: `git add` the new merge revision file.

**Phase 5 done when:** `... migrate heads` shows one head and a fresh DB upgrades to head cleanly.

## Phase 6: Account for the curl_cffi → aiohttp transport refactor (PR #940)

**What this phase achieves:** Confirms upstream's transport rewrite didn't break our core client usage or our sidecars.

- [ ] Step 6.1: After the merge, search the tree for `curl_cffi`: `grep -rn curl_cffi app/`. Expect upstream to have removed it from `codex.py`, `proxy.py`, `proxy_websocket.py`. If any reference remains AND the dependency is gone from `pyproject.toml`, fix the import to the aiohttp-based path upstream introduced.
- [ ] Step 6.2: Confirm our sidecar clients still import their own HTTP layer (they use httpx/aiohttp directly, not the core curl_cffi clients). Run `grep -rn "curl_cffi" app/modules/*sidecar* app/modules/claude_sidecar app/modules/proxy/*sidecar*` and expect no hits.
- [ ] Step 6.3: Run the core client tests upstream changed: `uv run pytest tests/unit/test_codex_client.py tests/unit/test_http_client.py tests/unit/test_proxy_websocket_client.py -q`. Fix any breakage from the transport change (these are upstream's tests; expect them to pass once the merge is correct).

**Phase 6 done when:** No stale `curl_cffi` references remain and core client tests pass.

## Phase 7: Commit the merge

**What this phase achieves:** Records the merge as a single commit with an honest message.

- [ ] Step 7.1: Run `git status` and confirm no unmerged paths and all resolved files are staged.
- [ ] Step 7.2: Commit with a heredoc message summarizing: "Merge upstream/main (1.20.1) into fork; preserve sidecar + DeepSeek + pricing functionality; reconcile alembic heads; regenerate lockfiles."
- [ ] Step 7.3: Run `git log --oneline -3` and confirm the merge commit is on top with two parents (`git show --no-patch --format='%P' HEAD` shows two hashes).

**Phase 7 done when:** A single merge commit exists with both parents.

## Phase 8: Full verification (the real test)

**What this phase achieves:** Proves nothing was lost and the combined tree is green.

- [ ] Step 8.1: Run backend suite: `uv run pytest -q`. Compare against the Phase 1 baseline — there must be NO new failures. Investigate any new failure before proceeding.
- [ ] Step 8.2: Run frontend suite from `frontend/`: `npx vitest run`. Compare to baseline; no new failures.
- [ ] Step 8.3: Run `uv run ruff check .` and fix any lint introduced by the merge.
- [ ] Step 8.4: Run `openspec validate --specs` and confirm clean.
- [ ] Step 8.5: Spot-check our sidecar features survived by confirming key files are intact and non-empty: `app/modules/proxy/sidecar_routing.py`, `app/modules/proxy/deepseek_v4_compat.py`, `app/core/usage/pricing.py`, `app/modules/ollama_sidecar/service.py`, `app/modules/openrouter_sidecar/service.py`, `app/modules/omniroute_sidecar/service.py`.
- [ ] Step 8.6: Run our sidecar-specific tests as a targeted gate: `uv run pytest tests/unit/test_sidecar_routing.py tests/unit/test_deepseek_v4_compat.py tests/unit/test_pricing.py tests/integration/test_ollama_sidecar_routing.py -q`. All must pass.
- [ ] Step 8.7: Run upstream's new test files to confirm we absorbed their behavior: `uv run pytest tests/integration/test_reports_api.py tests/unit/test_guard_stable_release.py -q`.
- [ ] Step 8.8: Build the frontend to catch type/import breakage from merged TS: `cd frontend && npm run build` (or the repo's build command). Confirm it succeeds.

**Phase 8 done when:** Backend + frontend suites match-or-beat baseline, lint clean, OpenSpec clean, frontend builds, and sidecar/DeepSeek/pricing tests pass.

## Phase 9: Manual smoke (optional but recommended, requires service restart)

> Only do this when the user confirms it is safe to restart the shared `codex-lb` service.

- [ ] Step 9.1: Ask the user to confirm a restart is safe (shared instance serves other agents).
- [ ] Step 9.2: On confirmation: `systemctl --user restart codex-lb.service`.
- [ ] Step 9.3: Load the dashboard; confirm the "External Integrations" card with Claude/OpenRouter/OmniRoute/Ollama tabs renders.
- [ ] Step 9.4: Confirm the new upstream features appear (guest read-only access, reports visualization, dashboard account list view).
- [ ] Step 9.5: Send one real request through a sidecar route and confirm a Request Log row appears with correct provider name and cost.

**Phase 9 done when:** Dashboard shows both our integrations and upstream's new features, and a live sidecar request logs correctly.

## Final verification (checklist)

- [ ] `git status` clean; single merge commit with two parents.
- [ ] `uv run pytest -q` — no new failures vs Phase 1 baseline.
- [ ] `cd frontend && npx vitest run` — no new failures vs baseline.
- [ ] `uv run ruff check .` clean.
- [ ] `openspec validate --specs` clean.
- [ ] `... migrate heads` shows exactly one head; fresh DB upgrades to head.
- [ ] No `curl_cffi` references left where the dep was removed.
- [ ] All sidecar/DeepSeek/pricing source files present and tests green.
- [ ] Frontend builds.

## If something goes wrong

- [ ] Mid-merge, want to bail entirely: `git merge --abort`. Tree returns to pre-merge `merge/upstream-1.20.1` state.
- [ ] Already committed the merge but it's wrong: `git reset --hard backup/pre-upstream-merge` (this is why Step 0.4 made the backup branch).
- [ ] A single file resolved wrong: re-extract a clean side with `git checkout --ours <file>` or `git checkout --theirs <file>` (relative to the in-progress merge: "ours" = our fork, "theirs" = upstream), then redo the hand-merge.
- [ ] Alembic shows >1 head after Step 5.5: you missed a head — re-run heads, identify the orphan, and point the merge revision's `down_revision` tuple at all heads.
- [ ] New test failure you can't attribute: run the same test on `backup/pre-upstream-merge` to confirm it's merge-introduced, not pre-existing.
- [ ] Do NOT push, open a PR, or restart the service until every Final Verification box is checked.
