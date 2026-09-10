# Context: per-account model exclusion on CLIProxyAPI

## Why the field lives in CLIProxyAPI, not codex-lb

CLIProxyAPI owns Claude account selection. codex-lb forwards a request to the sidecar; the sidecar
skips credentials whose `excluded_models` patterns match the wire model and weighted-round-robins
among the rest. That skip is the failover. If codex-lb kept its own desired copy of the list, the two
would drift the moment someone edited an auth file, so the auth JSON stays the single source of truth,
exactly as it already does for `disabled` (Pause).

Pause and exclusion stack. Pause removes an account from every model; exclusion removes it from some
models. Excluding a model on one account while the only other account able to serve it is paused
correctly yields `model_not_found`, because no eligible client remains.

## Pattern matching

CLIProxyAPI matches each entry as exact, `prefix-*`, `*-suffix`, or `*substring*`. Values are stored as
CLIProxyAPI wire model ids, never codex-lb's `cc/`-prefixed alias form: a `cc/` value would never match
and the exclusion would silently do nothing.

The dashboard's family switches (a fixed set of well-known model families) are a frontend convenience
that expands to those same patterns. The backend accepts any pattern string and knows nothing about
families, model names, or accounts. Anything the switches do not cover is entered as a custom chip.

## Global `oauth-excluded-models` is out of scope

CLIProxyAPI's `config.yaml` also has a global `oauth-excluded-models` map. Setting a model there hides
it on *every* Claude credential, which is the opposite of the goal here: hiding a model on the one
account that lacks entitlement while leaving the entitled account able to serve it. This change never
writes `config.yaml`.

## Read path on CLIProxyAPI 7.2.135

`GET /v0/management/auth-files` in the deployed CLIProxyAPI version does not return `excluded_models`
in its list entries, though the write path (`PATCH /v0/management/auth-files/fields`) accepts it.
Authoritative read and credential-safety rules are specified in
[the backend contract](specs/dashboard-sidecar-management/spec.md#requirement-report-cliproxyapi-account-excluded-models).
A live auth file may already carry exclusions placed there by hand. These remain operator data,
not configuration owned by this change.

## Verification boundaries

The opt-in tests in `tests/contract/cliproxy_exclusions` compile into a clean checkout of pinned
CLIProxyAPI commit `856ddd8df746a38a6033dbbf6c140974bf5aea0f` through a Go overlay. They exercise
the real auth-file parser, registration, Manager selection and retry paths. A separate watcher case
saves and clears the exclusion on disk and observes the actual fsnotify event through CLIProxyAPI's
real update consumer and same-Manager selection. The provider executor is the only request-boundary
fake, and the macOS sandbox denies all network operations and writes to source, Git metadata, module
cache and this repository.

The separate real-handler contract in `tests/contract/cliproxy_exclusions/http` crosses codex-lb's
Python route and client boundary to CLIProxyAPI's management handler and FileTokenStore. Its test
bodies passed save, read-back and clear with synthetic accounts. The adapted public launcher has
not been executed. The preserved `tests/integration/test_claude_sidecar_excluded_models_contract.py`
full-main fixture remains unexecuted. Neither the native nor real-handler evidence covers full
application lifespan, live providers, production behavior or IPv6 endpoints.

## Normalization

See [the backend contract](specs/dashboard-sidecar-management/spec.md) for write normalization
and fail-closed read semantics, including lists that would change under normalization.
