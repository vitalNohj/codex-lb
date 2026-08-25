# OrcaRouter, OpenCode Zen, and OpenCode Free sidecar routing — context

## Overview

This change adds three first-class External Integrations that speak OpenAI-compatible HTTP, cloned from the OpenRouter sidecar rather than the Ollama SDK adapter.

OmniRoute already hosts all three. The point is to stop requiring OmniRoute for this traffic: Cursor → codex-lb → OrcaRouter / OpenCode Zen / OpenCode Free.

Implementer recipe: `plan.md` in this folder. Clone `openrouter_sidecar` files, not `ollama_sidecar`.

## Why not keep using OmniRoute?

OmniRoute remains the right home for unofficial web/session providers. These three do not need that stack:

- OrcaRouter: Bearer API key, `/v1/chat/completions`, namespaced model IDs.
- OpenCode Zen: Bearer Zen API key, same `/zen/v1` host, catalog IDs such as `mimo-v2.5-free`.
- OpenCode Free: no key, public `https://opencode.ai/zen/v1`, catalog IDs such as `big-pickle`.

Keeping them behind OmniRoute hides 401s from the keyless pool, combo failover, and upstream identity. First-class tabs make enable/prefix/key/health obvious in codex-lb Settings.

## Model identity

OrcaRouter's adaptive router id is `orcarouter/auto`. Sending bare `auto` returns 503 "No available channel". Seeded prefix `orcarouter/` therefore has strip **off**. Pinned OrcaRouter models use vendor ids (`openai/gpt-5.5`). Those collide with OpenRouter prefixes if seeded globally, so they are **full-model** rows the operator adds. Full-model exact match already beats any prefix.

OpenCode Zen and OpenCode Free live catalogs use bare ids (`mimo-v2.5-free`, `big-pickle`). Client-facing ids stay prefixed (`opencode-zen/mimo-v2.5-free`, `oc/big-pickle`). Seeded prefixes have strip **on**. Effective model stays on logs and API-key checks; wire model is the stripped id.

Do not seed `opencode/` on Free. Official OpenCode TUI uses `opencode/<id>` for Zen. Cursor through OmniRoute already uses `opencode-zen/`.

If OmniRoute already owns `orcarouter/`, `oc/`, or `opencode-zen/` in saved settings, enabling the new tabs with the seeded prefixes fails uniqueness until the operator removes the OmniRoute overlap. That is intentional.

## OpenCode Free vs OpenCode Zen vs OpenCode the client

- Request-log `useragent_group=opencode` already means the OpenCode **client** talking to codex-lb.
- New source `opencode_sidecar` / label **OpenCode Free** = keyless zen hop.
- New source `opencode_zen_sidecar` / label **OpenCode Zen** = authenticated zen hop.
- Do not conflate the three.

## Auth and health

OrcaRouter and OpenCode Zen are configured when enabled and an API key is stored. OpenCode Free is configured when enabled; test-connection and model discovery MUST run without a key. Outbound Authorization is omitted when the Free key is empty.

## Cost

`-free` suffix detection plus opaque ids `big-pickle`, `oc/big-pickle`, `opencode-zen/big-pickle`. OrcaRouter is paid: persist usage when present; leave `cost` null without a pricing row; do not write zero.

## Out of scope (explicit)

MiMoCode bootstrap JWT, DeepSeek Web PoW/userToken, OpenCode Go, OmniRoute combo stacks, per-fingerprint proxies, `/v1/responses` / Zen `/messages` dispatch, uninstalling OmniRoute.
