# Design: DeepSeek V4 Cursor Compatibility

## Problem

DeepSeek V4 thinking-mode models reject tool-call continuation turns when the
prior assistant message that emitted the `tool_calls` does not carry its
`reasoning_content` back in the request. The upstream error is:

```
400 reasoning_content in the thinking mode must be passed back
```

Cursor (and other OpenAI-compatible clients) do not echo `reasoning_content` on
assistant tool-call messages, so the second turn of any tool-using DeepSeek V4
conversation fails. codex-lb owns the OpenAI-compatible sidecar dispatch path
for these models (`oc/deepseek-v4-flash-free` and friends, routed through
OmniRoute / OpenRouter), so the repair belongs here, before the request leaves
the proxy.

Reference behavior: `yxlao/deepseek-cursor-proxy` — cache the assistant
`reasoning_content` observed on responses, and re-inject it into later
tool-call turns; for streaming, accumulate `reasoning_content` deltas.

## Scope / Non-goals

- Only DeepSeek V4 family models (`deepseek-v4-pro`, `deepseek-v4-flash`,
  provider-prefixed variants like `oc/deepseek-v4-flash-free`, and an
  operator-configurable alias list) routed through the OpenRouter / OmniRoute
  sidecar chat-completions path are intercepted.
- Native Codex, Claude/CLIProxyAPI, and all non-DeepSeek sidecar traffic are
  untouched (byte-for-byte pass-through).
- No new dashboard card, provider account type, or DeepSeek key management.
- Responses API routing, `/backend-api/codex/*`, and control endpoints are
  untouched.

## Detection

A single helper `is_deepseek_v4_model(model: str, aliases: frozenset[str])`
decides whether a request is in scope. Matching is case-insensitive and
prefix/suffix tolerant so provider-prefixed and `-free` suffixed forms match:

- Canonical family tokens: `deepseek-v4-pro`, `deepseek-v4-flash` (also the
  `_`/`-` interchangeable spellings, mirroring `prefix_variants`).
- A model matches if, after lowercasing, it equals an alias, or it contains a
  canonical family token as a path/segment component (e.g. `oc/deepseek-v4-flash-free`,
  `openrouter/deepseek/deepseek-v4-pro`).
- Aliases come from settings (new optional field; empty by default) and are
  matched as exact case-insensitive full-model strings.

Detection runs against the **effective model** (the un-stripped model the
client/router resolved), consistent with logging/quota, so the family token is
visible even when a strip-prefix would remove it from the wire model.

## Where the transform hooks in

Both `proxy_chat_to_openrouter` and `proxy_chat_to_omniroute` already build a
sidecar payload (`build_*_chat_payload`) and branch on `payload.stream`. The
DeepSeek repair is a thin, provider-agnostic layer applied around that:

1. **Request re-injection (outgoing):** after the sidecar body dict is built and
   before it is sent, if the request is in scope, walk `messages` and patch any
   assistant message that has `tool_calls` but is missing a non-empty
   `reasoning_content`, using the cache (keyed as below). This mutates only the
   sidecar body, never the client-facing `payload`.
2. **Response capture (incoming):**
   - Non-streaming: after a successful `chat_completion`, read
     `choices[].message.reasoning_content` and, when the assistant message has
     `tool_calls`, store it in the cache under the key derived from the
     **outgoing** conversation prefix + this new assistant turn.
   - Streaming: wrap the byte stream in a `DeepSeekReasoningStreamAccumulator`
     that parses `chat.completion.chunk` events, accumulates
     `choices[].delta.reasoning_content` string deltas and `delta.tool_calls`,
     and on stream completion (`finish_reason == "tool_calls"` / `[DONE]`)
     stores the accumulated reasoning in the cache. The accumulator yields all
     chunks through unchanged (pure observer; no rewrite of client bytes).

The DeepSeek layer is applied **inside** the provider dispatch functions, ahead
of the existing `cursor_compat` wrappers, so Cursor usage-fallback rewriting and
keepalive injection continue to operate on the final byte stream unchanged. The
DeepSeek stream observer wraps the raw sidecar iterator (the same place the
provider's own `_*_stream_iterator` is created), so settlement/logging in that
iterator is preserved and the observer only reads chunks already yielded.

## Cache key strategy

The cache maps a **logical conversation prefix** to the `reasoning_content` of
the assistant tool-call turn that should follow it. Key inputs (all hashed
together with SHA-256, hex digest):

- The **canonical conversation prefix**: the ordered list of messages up to and
  including the assistant tool-call message whose reasoning we are keying, with
  `reasoning_content` itself **excluded** from the canonicalization (so the key
  computed when storing — from a response — matches the key computed when
  re-injecting — from a later request that lacks reasoning). Canonicalization:
  JSON-serialize a reduced view of each message — `role`, `content` (normalized
  to a stable string/parts form), and for assistant tool-call turns the ordered
  `tool_calls` reduced to `(id, function.name, function.arguments)`. Tool
  messages reduce to `(role, tool_call_id, content)`.
- **Provider** (`openrouter` / `omniroute`).
- **Model family token** (the canonical `deepseek-v4-pro` / `deepseek-v4-flash`,
  not the full provider-prefixed string) — so a pro/flash switch does not reuse
  reasoning.
- **API-key hash**: SHA-256 of the API key id (or `"anon"` when no key) — so
  reasoning never crosses API keys.

Storing (from a response): the prefix is the outgoing request's messages plus
the **new** assistant tool-call turn synthesized from the response
(`tool_calls` from the response message / accumulated deltas). Re-injecting
(from a later request): for each assistant tool-call message missing reasoning,
compute the key from the prefix ending at that message and look it up.

This makes the key reproducible across the store/lookup boundary and isolates by
conversation content, provider, model family, and API key.

## Bounded retention store

`DeepSeekReasoningCache`: an in-process LRU with a hard entry cap
(`maxsize`, default 2048) and a TTL (default 30 minutes). Implemented over an
`OrderedDict[str, _Entry]` guarded by a `threading.Lock` (writes happen from
async background-ish contexts but the critical section is tiny and sync).
`get` evicts expired entries lazily and moves hits to the end; `set` inserts and
evicts the oldest when over capacity. A module-level singleton is used by the
dispatch layer; tests construct their own instance for isolation. No external
storage (Redis) — reasoning is best-effort and ephemeral, matching the
non-goal "do not guarantee recovery for never-observed conversations."

## Partial-failure / stop-stream handling

- The streaming observer is a **pure pass-through**: it must yield every chunk
  it receives in order and must not swallow or alter error chunks. It only
  *reads* deltas to accumulate reasoning.
- Reasoning is committed to the cache **only** when the stream reaches a clean
  tool-call completion (`finish_reason == "tool_calls"` observed, followed by
  `[DONE]`). If the stream errors, is interrupted, or ends without a tool-call
  finish, nothing is cached (so a half-formed reasoning string is never
  re-injected). This piggybacks on the provider iterator's existing
  `completed`/`settled` flags conceptually but is tracked independently inside
  the observer.
- Cache reads/writes are wrapped so any exception is swallowed and logged at
  `warning`; a cache failure must never break the proxied request. Re-injection
  failures fall back to forwarding the request unchanged (missing-cache
  behavior).
- Existing reservation settlement/release and request-log writes live in the
  provider iterators and are **unchanged**; the DeepSeek observer wraps the
  outer byte stream and never short-circuits those code paths.

## Missing-cache fallback

When no cached reasoning exists for a given assistant tool-call turn, the
request is forwarded unchanged. This means imported/old conversations whose
reasoning codex-lb never observed may still fail upstream — explicitly a
non-goal to recover. The first failing turn for a fresh conversation is
unavoidable only if the *first* assistant turn already lacked reasoning at the
client; in practice codex-lb observes the assistant turn's reasoning from the
response that produced the `tool_calls`, then re-injects it on the very next
tool-result turn.

## Cursor usage fallback compatibility

The DeepSeek layer runs strictly before the `cursor_compat` usage-fallback
wrappers and does not touch `usage`, `choices` shape, or the synthetic
context-limit chunks. Cursor usage-fallback semantics (synthetic prompt/completion
token estimates, context-limit error → compaction trigger) are preserved
unchanged for DeepSeek traffic.

## Files

- New: `app/modules/proxy/deepseek_v4_compat.py` — detection, cache, request
  re-injection, non-streaming capture, streaming accumulator/observer.
- Modified: `app/modules/proxy/openrouter_sidecar_dispatch.py`,
  `app/modules/proxy/omniroute_sidecar_dispatch.py` — invoke the DeepSeek layer
  around payload build / response handling when in scope.
- Modified (optional alias config): dashboard settings model + sidecar config
  dataclasses to surface an operator alias list; defaults empty so behavior is
  unchanged when unset.
- Tests: `tests/.../test_deepseek_v4_compat.py` (unit) + dispatch-path
  integration tests.
