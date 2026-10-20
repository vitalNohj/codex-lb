# Troubleshooting

## Usage and quota

**Why does codex-lb still say `rate_limited` when Codex Desktop says the window reset?**
codex-lb refreshes usage on its own schedule and treats upstream samples conservatively. The full policy — refresh cadence, expiry, and why displays can briefly disagree with upstream — is documented in the
[usage refresh policy context](https://github.com/Soju06/codex-lb/blob/main/openspec/specs/usage-refresh-policy/context.md).

**Why does `/v1/responses` return a quota error instead of waiting for recovery?**
See the [Responses capacity recovery contract](https://github.com/Soju06/codex-lb/blob/main/openspec/specs/responses-api-compat/spec.md#requirement-capacity-recovery-preserves-terminal-errors-and-bounds-silent-waits) for terminal error classification, silent-wait limits, and `Retry-After` behavior. Error propagation does not restore exhausted upstream account capacity.

**Why do Claude requests through CLIProxyAPI fail with `cliproxy_claude_route_unavailable`?**
codex-lb sends a Claude request only with its CLIProxyAPI credential prefix, so the conversation stays on the account holding its prompt cache. The `503` means no prefixed credential could serve it: CLIProxyAPI capacity routing is off, no prefixed credential lists the model, or the selection failed. The `cliproxy_route_outcome` log line and `codex_lb_cliproxy_route_outcome_total{outcome="refused"}` say which. See [Claude prompt caching through CLIProxyAPI](../README.md#claude-prompt-caching-through-cliproxyapi).

**Why do pinned Claude conversations show no cached input tokens?**
CLIProxyAPI must reach `api.anthropic.com` directly. A gateway that rewrites request bodies in between makes every Claude turn a full cache write, which the `CodexLBClaudeStickyCacheMiss` alert and the `cliproxy_claude_sticky_cache_miss` log line report. Prompts under 4,096 tokens are not counted, because a prompt below its model's minimum is never cached. A conversation idle past the cache TTL misses once, which does not reach the alert's rate.

## Streaming

**Codex CLI falls back to POST instead of WebSockets.**
Run the [WebSocket verification steps](client-setup.md#verify-websocket-transport). If codex-lb sits behind a reverse proxy, make sure it forwards WebSocket upgrades — see [Remote Access](deployment/remote.md).

## Fast Mode, Ultrafast, and service tiers

Fast Mode, Ultrafast, and service-tier behavior is documented in the
[Responses API compatibility context](https://github.com/Soju06/codex-lb/blob/main/openspec/specs/responses-api-compat/context.md#fast-mode-and-service-tiers).

## Old Codex sessions missing after migrating

`codex resume` filters by `model_provider` — re-tag old sessions with the built-in retag command. See
[session retagging](client-setup.md#migrating-from-direct-openai-session-retagging).

---

*Spec: [usage-refresh-policy](https://github.com/Soju06/codex-lb/tree/main/openspec/specs/usage-refresh-policy)*
