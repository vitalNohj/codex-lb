## Context

`proxy_chat_to_orcarouter` forwards one Chat Completions call to `api.orcarouter.ai` and returns the first HTTP result. Provider failures observed in request logs are HTTP 524 after ~300s (Cloudflare waiting on an origin that never answered) and HTTP 502 HTML from Tencent STGW (the gateway in front of Z.ai). Neighboring calls to the same model succeed, including ones that run longer than 300s once a response has started. OrcaRouter chooses the upstream provider. A second identical request is the lever that lets it pick a different one. codex-lb does not select OrcaRouter providers itself.

The configured request timeout is 600s per attempt. The 300s cutoff is upstream of this process.

## Goals / Non-Goals

**Goals:**

- One extra attempt when OrcaRouter reports a provider or transport failure and the client has received nothing yet.
- Streaming and non-streaming share that rule.
- The request log records the final outcome once.

**Non-Goals:**

- Retrying other sidecars.
- Retrying HTTP 4xx, including context-length errors.
- Retrying after any streamed byte has been sent.
- A new setting, backoff, or request-log column.
- Changing the per-attempt timeout.

## Decisions

1. Retry inside `orcarouter_sidecar_dispatch.py`, not the HTTP client. The client stays a single POST. The dispatch path owns "has the client seen bytes yet" and settlement.
2. Retry when `OrcaRouterSidecarError.status_code >= 500`. That covers 500, 502, 503, 504, and 524. `OrcaRouterSidecarUnavailableError` is a 503, so connection failures and timeouts are included. 4xx is not.
3. Exactly one extra attempt, immediately, with the same payload. No sleep. OrcaRouter's reroute happens on the new request.
4. On a stream, retry only when the generator has not yielded. A mid-stream failure still becomes one SSE error, matching today's behavior.
5. Settlement and the request log stay in the existing `finally` / error paths, so a retried success writes one success row and a double failure writes one error row. Latency covers both attempts.

## Risks / Trade-offs

- A 524 retry can add another ~300s before the client sees an error. That is the cost of giving OrcaRouter a second provider. The alternative is the current immediate failure.
- The second attempt can hit the same provider. Nothing in this process forces OrcaRouter's choice.
- A non-idempotent tool call that failed before any byte is sent is still safe to repeat, because the model produced no output.

## Migration Plan

Deploy with the next process restart. Rollback is reverting the dispatch retry. No schema change.

## Open Questions

None.
