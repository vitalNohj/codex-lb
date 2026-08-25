# OrcaRouter and OpenCode Free sidecar routing — context

## Overview

This change adds two first-class External Integrations that speak OpenAI-compatible HTTP, cloned from the OpenRouter sidecar rather than the Ollama SDK adapter.

OmniRoute already hosts both providers. The point of this change is to stop requiring OmniRoute for this traffic: Cursor → codex-lb → OrcaRouter or OpenCode zen.

## Why not keep using OmniRoute?

OmniRoute remains the right home for unofficial web/session providers. OrcaRouter and OpenCode Free do not need that stack:

- OrcaRouter: Bearer API key, `/v1/chat/completions`, namespaced model IDs.
- OpenCode Free: no key, public `https://opencode.ai/zen/v1`, catalog IDs such as `big-pickle` and `deepseek-v4-flash-free`.

Keeping them behind OmniRoute hides 401s from OpenCode's keyless pool, combo failover, and upstream identity. First-class tabs make enable/prefix/key/health obvious in codex-lb Settings.

## Model identity

OrcaRouter's adaptive router id is `orcarouter/auto`. Sending bare `auto` returns 503 "No available channel". Seeded prefix `orcarouter/` therefore has strip **off**. Pinned OrcaRouter models use vendor ids (`openai/gpt-5.5`, `google/gemini-3.5-flash`). Those collide with OpenRouter prefixes if seeded globally, so they are **full-model** rows the operator adds. Full-model exact match already beats any prefix.

OpenCode Free's live catalog uses bare ids (`big-pickle`). Client-facing ids stay prefixed (`oc/big-pickle`, `opencode/big-pickle`). Seeded prefixes `oc/` and `opencode/` have strip **on**. Effective model stays on logs and API-key checks; wire model is the stripped id.

If OmniRoute already owns `oc/` in saved settings, enabling OpenCode Free with the seeded prefixes fails uniqueness until the operator removes the OmniRoute overlap. That is intentional.

## OpenCode Free vs OpenCode the client

Request-log `useragent_group=opencode` already means the OpenCode **client** talking to codex-lb. The new source is `opencode_sidecar` with account label **OpenCode Free**. Do not conflate the two.

## Auth and health

OrcaRouter is configured when enabled and an API key is stored. OpenCode Free is configured when enabled; test-connection and model discovery MUST run without a key. Outbound Authorization is omitted when the key is empty.

## Cost

OpenCode Free is treated as free via existing `-free` detection plus opaque ids such as `oc/big-pickle`. OrcaRouter is paid: persist usage when present; leave `cost` null without a pricing row; do not write zero.

## Out of scope (explicit)

MiMoCode bootstrap JWT, DeepSeek Web PoW/userToken, OpenCode Zen paid / Go, OmniRoute combo stacks, per-fingerprint proxies, `/v1/responses` dispatch.
