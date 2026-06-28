# Tasks

## 1. Management client passthrough

- [x] 1.1 Add `ClaudeSidecarClient.api_call(auth_index, method, url, header)` posting to `POST /v0/management/api-call` with the Management Bearer key, parsing the `{status_code, body}` wrapper, mapping upstream `status_code >= 400` to `ClaudeSidecarError` and transport failures to `ClaudeSidecarUnavailableError`.

## 2. OAuth usage fetch via CLIProxyAPI

- [x] 2.1 Rewrite `fetch_claude_oauth_usage(client, auth_index)` to call `client.api_call` with `Authorization: Bearer $TOKEN$` and `anthropic-beta` against `oauth/usage`, feeding the body into `parse_claude_oauth_usage`.
- [x] 2.2 Delete `ClaudeOAuthCredential`, `load_claude_oauth_credential`, and the sync disk-read helper.

## 3. Poller enrichment

- [x] 3.1 Drive `_attach_oauth_usage` by `account.auth_index` through the client; skip enrichment when `auth_index` is missing.
- [x] 3.2 Preserve never-store-token, carry-forward-on-failure, and leave-none-without-prior semantics.

## 4. Tests

- [x] 4.1 Update `test_claude_sidecar_oauth_usage.py` to assert the posted `auth_index`, URL, `$TOKEN$` header, and `anthropic-beta`, plus upstream-error mapping.
- [x] 4.2 Update `test_claude_sidecar_quota_poller.py` enrichment tests to drive by `auth_index` via the fake client.
- [x] 4.3 Add `api_call` cases to `test_claude_sidecar_client.py` (success, upstream 4xx, transport failure).

## 5. Validation

- [x] 5.1 `openspec validate route-claude-oauth-usage-via-cliproxy --strict`.
- [x] 5.2 `uv run pytest` for the three touched test modules; `uv run ruff check` for the touched app modules.
