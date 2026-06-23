# Route Claude OAuth Usage Through CLIProxyAPI

## Why

The Claude sidecar quota poller enriches each auth's snapshot with Anthropic's
authoritative 5-hour/7-day OAuth usage percentages. Today codex-lb fetches
those percentages itself: it reads the credential file off disk to recover the
account `access_token` and calls `https://api.anthropic.com/api/oauth/usage`
directly from the codex-lb process.

This violates the egress contract. CLIProxyAPI configures a per-account
`proxy-url` so that every upstream Anthropic call for an account rides that
account's proxy. By calling Anthropic directly, codex-lb (a) bypasses that
proxy egress, (b) handles a sensitive long-lived OAuth token it should never
touch, and (c) couples the poller to credential-file layout on disk.

CLIProxyAPI exposes `POST /v0/management/api-call`, a generic passthrough that
resolves a credential by `auth_index`, substitutes the `$TOKEN$` marker with
that credential's token, and routes the request through the account's
configured proxy. CLIProxyAPI itself does not expose the rolling-window
percentages, so Anthropic's `oauth/usage` remains the only authoritative
source — but we can reach it through CLIProxyAPI instead of directly.

## What Changes

- Add an `api_call()` method to `ClaudeSidecarClient` that posts to
  `POST /v0/management/api-call` with the Management Bearer key, parses the
  `{status_code, body}` wrapper, maps upstream `status_code >= 400` to a
  sidecar error, and returns the decoded JSON body.
- Rewrite the Claude OAuth usage fetch to call Anthropic's `oauth/usage`
  endpoint via `api_call()` keyed by `auth_index`, sending
  `Authorization: Bearer $TOKEN$` and `anthropic-beta: oauth-2025-04-20`.
- Remove the on-disk credential read path entirely (`ClaudeOAuthCredential`,
  `load_claude_oauth_credential`); codex-lb no longer reads credential files or
  calls Anthropic directly.
- Drive poller enrichment by `auth_index`; preserve the existing
  carry-forward-on-failure, never-store-token, and leave-none-without-prior
  semantics.

## Impact

- Affected specs: `dashboard-sidecar-management`
- Affected code: `app/core/clients/claude_sidecar.py`,
  `app/modules/claude_sidecar/oauth_usage.py`,
  `app/modules/claude_sidecar/quota_poller.py`
- Egress/behavior: OAuth usage now egresses through each account's configured
  CLIProxyAPI proxy; codex-lb makes no direct Anthropic call and reads no
  credential files. No new settings; reuses the existing Management API key.
