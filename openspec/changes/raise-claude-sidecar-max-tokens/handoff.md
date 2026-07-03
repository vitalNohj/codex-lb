# Agent handoff: Cursor `max_tokens: 4096` ceiling on Claude sidecar (Fable 5 / Opus)

Use this document as the full context for implementing a fix. Read it before touching code.

---

## Your mission

Investigate is done. **Implement a minimal, safe fix** so Claude sidecar requests (CLIProxyAPI path) are not stuck at Cursor’s per-turn `max_tokens: 4096` output ceiling when the model needs more budget for thinking + tool calls.

Do **not** restart `codex-lb.service` unprompted (shared instance). Do **not** expand scope into unrelated sidecar/UI work unless required.

---

## Problem summary (user-visible)

When using **Fable 5** (`cc/claude-fable-5` or similar) through **Cursor → codex-lb → CLIProxyAPI**, the agent can spin forever (“taking longer than expected”) while **burning tokens**. codex-lb logs show `success`; CLIProxyAPI returns HTTP 200. The failure is behavioral, not a proxy crash.

---

## Root cause chain (confirmed)

1. **Cursor BYOK custom-model path** hits `/v1/chat/completions` (not native Codex Responses path).
2. Cursor sends **`max_tokens: 4096`** on every agent turn (verified in saved CLIProxyAPI request payloads). This is a **per-turn output ceiling**, not context window.
3. codex-lb Claude sidecar **passes `max_tokens` through unchanged** (`build_sidecar_chat_payload()` → `model_dump()`; `sanitize_sidecar_forward_payload()` does not strip it).
4. Operator setting **`claude_sidecar_default_reasoning_effort = xhigh`** forces heavy thinking. CLIProxyAPI logs: `level=max`.
5. On long agent threads (~**146k input tokens**), Fable/Opus can spend the **entire 4096 output budget on thinking** with little/no usable content or complete tool calls → `finish_reason: length` behavior (output_tokens exactly 4096).
6. Cursor does not advance → **retries ~every 60s** with the same fat context → token burn loop.

This is **not** inadvertent breakage. It is a **mismatch**: Cursor’s conservative BYOK default vs thinking-heavy Claude models under forced `xhigh`.

---

## Evidence (local production DB + logs)

**Workspace DB:** `~/.codex-lb/store.db`, table `request_logs`.

| Signal | Value |
|--------|-------|
| Route | `source = claude_sidecar`, models like `cc/claude-fable-5`, `cc/claude-opus-4-8` |
| Bad pattern | `output_tokens = 4096` exactly, `latency_ms` ~60k, every ~60s |
| Claude sidecar 14d | **~19%** of requests hit exactly 4096 output (1531 / 8123) |
| Fable 14d | 329 slow (50s+) turns avg ~4056 output; 1461 fast turns avg ~835 output |
| Native Cursor → `gpt-5.5` | **0%** at exactly 4096; outputs **11k+** seen — different Cursor code path |

**CLIProxyAPI saved payloads** (`~/.cli-proxy-api/logs/error-v1-chat-completions-*.log`):

```
max_tokens: 4096
max_completion_tokens: null
stream: true
reasoning_effort: xhigh
model: claude-fable-5
```

**CLIProxyAPI** accepts higher values (tested 8k/16k/64k — no 400).

---

## Why Cursor sends 4096 (not codex-lb)

- **Not universal Cursor limit.** Native Codex (`gpt-5.5`) through codex-lb uses Responses-ish path; `to_responses_request()` **drops** `max_tokens`. Those requests are not capped at 4096.
- **Custom Claude BYOK** uses legacy `/v1/chat/completions`. Cursor fills in a **generic OpenAI-compat default (4096)** when it has no catalog metadata for the custom model.
- Intent (inferred, not malice): conservative **per-turn output cap** for BYOK cost control + agent steps assumed small. **No UI** to configure output limit for custom models (Cursor forum: custom models get assumed ~1M **input** context, but output cap stays generic).
- **4096 is resent every agent turn** — not session-scoped. Each retry includes `max_tokens: 4096` again.

---

## Is raising `max_tokens` safe?

**Yes, with per-model ceilings.** Unlikely to break Cursor protocol or CLIProxyAPI.

| Risk | Notes |
|------|-------|
| Higher cost per turn | Model bills actual tokens; still cheaper than retry loops replaying 146k input |
| Longer single-turn latency | Possible; better than infinite retry |
| Context overflow | `input + max_tokens` must fit model window; at ~146k in + 128k cap on 1M models, usually fine |
| Thinking still eats budget | Raising cap helps but **`xhigh` effort** may still burn budget on thinking alone — consider pairing with effort guidance in context docs |
| Override philosophy | User treats operator settings as true overrides; raising client `max_tokens` is proxy correcting Cursor’s BYOK default |

**Do not** set above model’s published max (upstream 400).

---

## Official model output limits (Anthropic)

**Human table:** https://platform.claude.com/docs/en/about-claude/models/overview

| Model | Context | Max output (sync Messages API) |
|-------|---------|-------------------------------|
| Claude Fable 5 (`claude-fable-5`) | 1M | **128k** |
| Claude Opus 4.8 (`claude-opus-4-8`) | 1M | **128k** |
| Claude Sonnet 5 | 1M | 128k |
| Claude Haiku 4.5 | 200k | 64k |
| Claude Sonnet 4.5 (legacy) | 200k | 64k |

**Machine-readable:** Anthropic `GET /v1/models` returns `max_tokens` and `max_input_tokens` per model.

**Fable note:** Always-on adaptive thinking. `max_tokens` budget includes **thinking + visible output + tool JSON** together.

---

## Existing codex-lb precedent

Native Codex already has per-model output caps for `/v1/models` advertisement:

```python
# app/modules/proxy/api.py
_V1_MAX_OUTPUT_TOKEN_OVERRIDES = {
    "gpt-5.4": 128_000,
    "gpt-5.5": 128_000,
    ...
}
```

Claude sidecar models use `_SIDECAR_DEFAULT_CONTEXT_WINDOW = 200_000` on `/v1/models` — **understates** Fable/Opus 1M context. Separate improvement; related theme (Cursor not learning real limits).

**Pricing table** (`app/core/usage/pricing.py`) has Claude model IDs but **no output limits**.

**Canonical model resolution:** `app/modules/proxy/sidecar_model_profiles.py` → `canonical_sidecar_model()`.

**Payload build hook:** `app/modules/proxy/claude_sidecar_dispatch.py` → `build_sidecar_chat_payload()`.

---

## Implementation guidance

### Apply per request, not once per chat

- Logic lives in one place (e.g. `build_sidecar_chat_payload()` or helper called from there).
- Runs on **every** incoming Claude sidecar chat request.
- Cursor resends `max_tokens: 4096` each turn; no session bootstrap to set once.

### Suggested policy

```text
client = body.get("max_tokens")  # usually 4096 from Cursor
floor = MODEL_OUTPUT_FLOOR[canonical_model]  # e.g. 16_384 or 32_768
cap   = MODEL_OUTPUT_CAP[canonical_model]    # e.g. 128_000 for Fable/Opus
body["max_tokens"] = min(max(client or 0, floor), cap)
```

Optional: `min(..., context_window - estimated_input)` when input is huge (defensive).

**Conservative first ship:** floor **16k–32k** (fixes most 4096 cap-hits without max cost exposure). Can tune from `request_logs` where `output_tokens = 4096`.

### Scope boundaries

- **In scope:** Claude sidecar chat-completions forward path only (`claude_sidecar_dispatch.py`).
- **Out of scope unless necessary:** native Codex Responses path (already drops `max_tokens`), OpenRouter/OmniRoute sidecars, codex-lb restart, effort override changes.
- **OpenSpec:** Behavior change → create/update `openspec/changes/raise-claude-sidecar-max-tokens/` with `spec.md` (MUST/SHALL on first line), tests, validate before PR.

### Tests to add

- Unit: `build_sidecar_chat_payload()` with `max_tokens=4096` + Fable/Opus model → raised to floor.
- Unit: client sends `max_tokens=64000` → unchanged (or capped at model max only).
- Unit: unknown Claude model → sensible default or no-op.
- Regression: `sanitize_sidecar_forward_payload` behavior unchanged.

### What NOT to do

- Do not use codex-lb dashboard in-UI OmniRoute updater patterns here.
- Do not restart `codex-lb.service` without user confirmation.
- Do not only fix `/v1/models` advertisement without fixing forward path (Cursor still sends 4096 in body).
- Do not assume fixing `max_tokens` alone fixes all Fable hangs if `xhigh` still burns entire budget on thinking.

---

## Related operator mitigations (no code)

1. Lower `claude_sidecar_default_reasoning_effort` from `xhigh` to `medium`/`high` in dashboard settings.
2. Start fresh Cursor chat / compact to drop ~146k context replay.
3. Stop runaway agent to break retry loop.

---

## Key files

| File | Role |
|------|------|
| `app/modules/proxy/claude_sidecar_dispatch.py` | Payload build + forward; **primary fix location** |
| `app/modules/proxy/sidecar_model_profiles.py` | Canonical model IDs |
| `app/core/usage/pricing.py` | Claude model aliases (pricing only today) |
| `app/modules/proxy/api.py` | `_V1_MAX_OUTPUT_TOKEN_OVERRIDES` precedent; sidecar `/v1/models` context |
| `app/core/openai/chat_requests.py` | `max_tokens` field; stripped on Responses conversion only |
| `tests/unit/test_claude_sidecar_dispatch.py` | Existing sidecar dispatch tests |

---

## Verification after implement

1. `uv run pytest tests/unit/test_claude_sidecar_dispatch.py` (and new tests).
2. `openspec validate raise-claude-sidecar-max-tokens --strict` if spec added.
3. Manual: direct sidecar call through codex-lb with Cursor-like body (`max_tokens: 4096`, `reasoning_effort: xhigh`, tools, large messages) — confirm forwarded payload shows raised `max_tokens`.
4. Check `request_logs` after real Cursor traffic: fewer rows with `output_tokens = 4096` + 60s latency loop.

---

## Prompt for the implementing agent

```
You are fixing a Cursor + codex-lb + CLIProxyAPI issue where Claude sidecar models
(Fable 5, Opus 4.8) hit output_tokens=4096 every ~60s in a retry loop while Cursor
spins. Root cause: Cursor sends max_tokens:4096 on every BYOK chat-completions
turn; xhigh thinking burns the full budget; codex-lb passes it through unchanged.

Read: openspec/changes/raise-claude-sidecar-max-tokens/handoff.md

Implement minimal fix: per-request floor (and model cap) on max_tokens in
build_sidecar_chat_payload() for Claude sidecar only. Use canonical_sidecar_model()
for lookup. Precedent: _V1_MAX_OUTPUT_TOKEN_OVERRIDES in api.py. Anthropic caps:
Fable/Opus 128k max output (docs.platform.claude.com models overview).

OpenSpec first if behavior change. Unit tests required. Do not restart codex-lb.
Do not touch native Codex path. Start conservative (16k-32k floor). Keep diff small.
```
