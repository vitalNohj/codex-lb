# Handoff: GPT-5.6 Sol Cursor compaction

**Goal:** Make Cursor auto-compact when `gpt-5.6-*` (esp. Sol) sits near upstream context ceiling.

**Do NOT:** re-diagnose “Responses path missing Cursor compat” as the Sol fix. Do NOT revive empty-stream Claude retry architecture.

---

## Verdict (proven)

Existing Cursor compat only fires on **context-length errors** → synthetic success with `prompt_tokens=1_000_000`.

GPT-5.6 Sol near the ceiling returns **HTTP 200 success** with high usage (~350k–368k input). **No** `context_length_exceeded`. So error-path compaction **never runs**. Cursor UI can still show ~1M headroom → no auto-compact → chat sticks.

Traffic path: Cursor → `POST /v1/chat/completions` (`useragent=Cursor/1.0`). Chat path already has Cursor usage rewriting. Sol does **not** need “wire every surface” to fix this; it needs a **model exception on successful usage**.

---

## Live DB evidence (`~/.codex-lb/store.db`)

High Sol rows (all `status=success`, `error_code=NULL`):

| id | input_tokens | output_tokens |
|----|--------------|---------------|
| 81725 | 366841 | 881 |
| 81721 | 352800 | 391 |
| 81718 | 353188 | 102 |
| 81512 | 351802 | 1664 |
| 81508–81505 | ~350k | … |

No `context_length_exceeded` on these. `cursor_context_limit_fallback` historically seen for models like `gpt-5.5-extra`, not Sol.

Registry notes (context only, not the fix):

- Bootstrap Sol: `context_window=372_000`, `auto_compact_token_limit=None`
- Live/other metadata also showed `~272_000` for Sol family
- gpt-5.4 advertises `max_context_window=1_000_000`
- Cursor UI meter ≠ upstream Sol ceiling → accounting mismatch

---

## Intended fix (minimal)

**File:** `app/modules/proxy/cursor_chat_compat.py` only (plus tests).

1. Detect Cursor once (`is_cursor_compat_client`) — already done at call sites.
2. Model exception: if `model.lower().startswith("gpt-5.6-")` AND chat `usage.prompt_tokens >= 350_000`, rewrite usage to synthetic compaction:
   - `prompt_tokens = 1_000_000` (`CURSOR_CONTEXT_LIMIT_SYNTHETIC_USAGE_TOKENS`)
   - `total_tokens = 1_000_000 + completion_tokens`
3. Hook in existing chat usage handlers (already partially done in **uncommitted** working tree):
   - `apply_cursor_usage_fallback`
   - `apply_cursor_usage_fallback_to_response`
   - `CursorChatSseCompatRewriter` usage-chunk path
4. Log: `cursor_proactive_compaction source=… model=… threshold=350000`

Threshold `350_000` chosen from observed stuck successes (~350k–368k). Prefer slightly under observed floor so compaction triggers before hard stick.

**Out of scope unless proven needed:**

- Responses `input_tokens` proactive rewrite (Cursor Sol uses chat; only add if live traffic proves Responses Sol stuck)
- Empty Claude 200 / CLIProxyAPI retry systems
- Expanding endpoint surface further for this bug

---

## Current git state

- Branch: `cloud/cursor-compat-all-surfaces-58c7`
- Tip: `f77ea2c2d` — all-surfaces Cursor context-limit PR (reapplied). Useful for error-path parity; **insufficient** alone for Sol.
- PR: https://github.com/vitalNohj/codex-lb/pull/11
- **Uncommitted** WIP in `cursor_chat_compat.py` (~+57 lines): helpers + hooks above. **No tests yet. Not restarted / not live.**

Inspect WIP:

```bash
cd /home/nohj/personal/codex-lb
git checkout cloud/cursor-compat-all-surfaces-58c7
git diff app/modules/proxy/cursor_chat_compat.py
```

---

## Finish checklist

1. Review WIP; keep asserts safe (`usage` None → skip via `is_json_mapping`).
2. Add focused unit/integration tests:
   - Cursor + `gpt-5.6-sol` + `prompt_tokens=350000` → rewritten to 1M
   - Cursor + Sol + `prompt_tokens=349999` → unchanged
   - Cursor + `gpt-5.5-*` high usage → unchanged (error-path only)
   - Non-Cursor + Sol high usage → unchanged
   - Streaming usage chunk path covered
3. Optional OpenSpec delta under existing change (behavior: proactive Sol compaction). Keep tiny; MUST/SHALL on first sentence if `--strict`.
4. `uv run pytest` on touched tests; frontend N/A if backend-only.
5. Commit + push branch; update PR #11.
6. Restart **only after user confirms safe**: `systemctl --user restart codex-lb.service` then `reset-failed` if needed. Confirm `:2455` healthy.
7. Verify live: next Sol Cursor turn ≥350k prompt should log `cursor_proactive_compaction` and Cursor should compact.

---

## Anti-patterns from prior session (do not repeat)

- Overbuilding “all surfaces” as the Sol fix while Sol never errors.
- Reverting Cursor work when user only wanted empty-response overbuild reverted.
- Restarting shared `codex-lb.service` mid-flight without confirmation.
- Thousands of lines / new OpenSpec empires for a threshold rewrite in one file.

---

## One-liner for next agent

> GPT-5.6 Sol succeeds at ~350k+ tokens without context errors; inflate chat `prompt_tokens` to 1M for Cursor when model is `gpt-5.6-*` and usage ≥350k. WIP already in `cursor_chat_compat.py` working tree — finish tests, commit, deploy.
