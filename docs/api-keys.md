# API Key Authentication

API key auth is **disabled by default**. In that mode, only local requests to the protected proxy routes can
proceed without a key; non-local requests are rejected until proxy authentication is configured. Enable it in
**Settings → API Key Auth** on the dashboard when clients connect remotely or through Docker, VM, or container
networking that appears non-local to the service.

When enabled, clients must pass a valid API key as a Bearer token:

```
Authorization: Bearer sk-clb-...
```

## Protected routes

The protected proxy routes covered by this setting are:

- `/v1/*` (except `/v1/usage`, which always requires a valid key)
- `/backend-api/codex/*`
- `/backend-api/transcribe`

## Creating keys

Dashboard → API Keys → Create. The full key is shown **only once** at creation. Keys support optional expiration, model restrictions, and rate limits (tokens / cost per day / week / month).

Keys can also be scoped to specific accounts, so a key draws quota only from the accounts assigned to it:

![API keys with assigned accounts](screenshots/apis-assigned-accounts.jpg)

## What a key holder can see

Besides proxying, a key can read some data about itself and its account pool. **Usage sections** (in the create and edit dialogs) decide what:

| Section | Grants | Default for new keys |
|---|---|---|
| Upstream limits | Pool-wide upstream quota: aggregate Codex windows in `/v1/usage`, and CLIProxyAPI credential quota in `/v1/quota-feed` | On |
| Account pool usage | The key's Codex account pool: pooled capacity in `/v1/usage` and the account list in `/api/fleet/summary` | On |
| Reset credits | Listing and redeeming the ChatGPT reset credits of the key's accounts at `/v1/reset-credit`. The listing includes account emails | **Off** |

With both Upstream limits and Account pool usage, a key also sees each account's email and usage in `/api/fleet/summary`, its rows in `/v1/quota-feed`, pool traffic in `/api/fleet/observability`, and may start `POST /api/fleet/refresh`. **Settings → Hide upstream quota from API keys** turns off everything the first two sections grant, and the `x-codex-*` quota headers on proxied responses, for every key. It does not change Reset credits.

A key always sees its own usage, limits and expiry in `/v1/usage`, and its own limits in `/api/codex/usage` (credit windows, plus cost and token limits under `additional_rate_limits`). Only enable Reset credits for keys you hold yourself: it lets the holder spend your ChatGPT reset credits.

### Capabilities by section

What an unshared key can reach, and what it needs:

| Capability | Endpoint | Needs |
|---|---|---|
| Own usage, limits and expiry | `/v1/usage`, `/api/codex/usage` | Always |
| Pool-wide upstream quota | `/v1/usage` `upstream_limits` | Upstream limits |
| CLIProxyAPI credential quota | `/v1/quota-feed` (Claude, xAI rows) | Upstream limits |
| Pooled Claude utilization | `/api/oauth/usage` | Always (empty while the privacy setting is on) |
| Pooled account capacity | `/v1/usage` `account_pool_usage` | Account pool usage |
| Account ids and status | `/api/fleet/summary` | Account pool usage |
| Account emails and per-account usage | `/api/fleet/summary`, Codex rows of `/v1/quota-feed` | Upstream limits and Account pool usage |
| Other traffic on the pool | `/api/fleet/observability` | Upstream limits and Account pool usage |
| Trigger a usage refresh | `POST /api/fleet/refresh` | Upstream limits and Account pool usage |
| List and redeem reset credits (with account emails) | `GET`/`POST /v1/reset-credit` | Reset credits |
| Warm up the pool's accounts | `POST /v1/warmup` | Always |
| Pool quota headers on responses | `x-codex-*` headers | Always (off while the privacy setting is on) |

### Shared keys

Turn on **Shared key** (create and edit dialogs) for a key you give to a friend or client. A shared key sees only its own usage, limits and expiry, whatever its usage sections say:

- `/v1/usage` and `/api/codex/usage` show only the key's own usage, limits and expiry.
- `/v1/reset-credit`, `/v1/quota-feed`, `/api/oauth/usage` and `/v1/warmup` answer `403 shared_api_key_not_allowed`; `/api/fleet/*` answers `403 permission_denied`.
- Proxied responses carry no `x-codex-*` quota headers.

While the toggle is on, the usage-sections picker is disabled. The sections are kept, so turning the toggle off restores what the key saw before. Shared keys carry a **Shared** badge in the key lists. New and existing keys are unshared.

## Reasoning effort policies

A key can either enforce one reasoning effort or allow a selected non-empty set of client-requested efforts.
Leave the allowed-efforts selection empty to keep the existing unrestricted behavior. A request that explicitly
sets an effort outside its key's allowlist receives a `403 reasoning_effort_not_allowed` response. Requests that
omit a reasoning effort continue to use the model or upstream default.

The policy evaluates the effort selected by the client, including supported model aliases such as `-xhigh`.
Each configured effort is distinct: allowing `high` does not allow `xhigh`, and allowing `max` does not allow
`ultra`. The proxy still rewrites an allowed `ultra` request to the upstream wire value `max`.

![API key reasoning-effort policy](screenshots/apis-reasoning-efforts.jpg)

For wiring keys into each client, see [Client Setup](client-setup.md).

---

*Spec: [api-keys](https://github.com/Soju06/codex-lb/tree/main/openspec/specs/api-keys)*
