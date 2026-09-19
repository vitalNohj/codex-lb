# Generic OpenAI-compatible endpoints

## Purpose

Let operators add any number of OpenAI-compatible Chat Completions bases (Vast.ai serverless, a vLLM box, LM Studio) as named External Integrations tabs, without cloning NVIDIA into another first-class sidecar.

## Why not a Vast sidecar

Vast is one of many OpenAI-compatible HTTP APIs. A dedicated tab would repeat NVIDIA's clone for every new host. A JSON list plus `+` is the same card N times.

## Vast wiring

Vast serverless OpenAI path is `https://openai.vast.ai/<ENDPOINT_NAME>/v1/chat/completions`. The stored base URL MUST be `https://openai.vast.ai/<ENDPOINT_NAME>/v1` because the client posts `{base}/chat/completions`. Direct vLLM is typically `http://INSTANCE_IP:PORT/v1`. The operator types that URL; the app does not pre-seed Vast.

## API keys

Optional. Vast usually has a key; local vLLM often does not. Encrypt at rest inside the JSON blob (Fernet bytes as base64). Never return the plaintext. Do not commit or log the key.

## What stays NVIDIA/OpenRouter-shaped

Enable, base URL, key, prefixes, full models, Discovered Models, effort override, timeouts, health, test connection, Chat Completions routing, synthetic account, HTTP request logs, DeepSeek V4 repair, reservation settlement.

## What is different

- List of endpoints, not columns per provider
- Provider/source ids are `openai_compat:{uuid}`
- Rank last vs first-class sidecars
- API key optional
- One dashboard filter for all generic endpoints
- No Free Model Discovery
- No invented prices; not per-request billed
