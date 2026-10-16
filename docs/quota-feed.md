# Quota feed

`GET /v1/quota-feed` reports per-account quota headroom for Codex accounts and for CLIProxyAPI credentials whose quota codex-lb has already stored (Claude OAuth usage, xAI Grok credits, and any other provider present in that snapshot).

The numbers come from the same account state the router uses to choose an account. A window the selector does not have data for is still listed, with `confidence` set to `unknown`.

The CLIProxyAPI account pool stays off until rollout. This endpoint does not change routing or any existing route. With the pool off, Codex accounts and stored sidecar quota are still reported.

## Authentication

The feed uses credentials codex-lb already issues. It does not add a key type or a key setting.

- A proxy API key in `Authorization: Bearer …`, the same key that calls `/v1/*`.
- A verified dashboard session cookie, or the trusted-header identity when the dashboard is configured for reverse-proxy auth.

Missing credentials and invalid credentials get `401`. A request that sends an `Authorization` header is checked as a proxy API key only; an invalid key does not fall through to a dashboard cookie. Passwordless local dashboard access is not a credential for this route.

An API key with account assignment scope sees only its assigned Codex accounts. Another key's assigned accounts are not included. CLIProxyAPI quota is pool-wide, because those credentials are not assigned per key and any proxy client can send that traffic.

## Response

`schemaVersion` is `1`. `generatedAt` and every `resetsAt` are ISO-8601 UTC.

`providers` is one row per account. Each row has `provider`, `accountKey`, and `windows`. `confidence` is `established` (a usage sample or quota poll), `estimated` (a rate-limit hold, or xAI token rollups that have counts but no percent), or `unknown`.

`perProvider` summarizes each provider that has at least one row: `accountsAvailable` is how many of those accounts are not paused, deactivated, reauthing, rate-limited, or quota-exceeded, and `maxHeadroomPercent` is the highest `percentRemaining` among the windows of those available accounts.

Window `source` values:

| Source | Where it comes from |
|---|---|
| `codex_usage` | Codex account usage the router reads |
| `anthropic_oauth_usage` | Claude sidecar OAuth buckets |
| `codex_oauth_usage` | A CLIProxyAPI Codex credential's OAuth buckets |
| `grok_credits_config` | xAI `GetGrokCreditsConfig` windows |
| `usage_queue_tokens` | xAI token rollup; percent is null |
| `unknown` | A provider the quota map does not interpret |

The response never includes tokens, API keys, credential paths, or account emails. `accountKey` is the router's account id (`acc-…` for Codex, `cliproxy:<provider>:<auth index>` for a sidecar credential).

Responses send `Cache-Control: private, max-age=15` and `Vary: Authorization, Cookie`.

## Example

```json
{
  "schemaVersion": 1,
  "generatedAt": "2026-10-16T07:45:00Z",
  "providers": [
    {
      "provider": "codex",
      "accountKey": "acc-123",
      "windows": [
        {
          "id": "five_hour",
          "kind": "rolling",
          "percentRemaining": 62.5,
          "resetsAt": "2026-10-16T12:00:00Z",
          "confidence": "established",
          "source": "codex_usage"
        }
      ]
    }
  ],
  "perProvider": {
    "codex": {"accountsAvailable": 1, "maxHeadroomPercent": 62.5}
  }
}
```
