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
in its list entries, though the write path (`PATCH /v0/management/auth-files/fields`) accepts it. So
the read path prefers `excluded_models` (or the hyphenated `excluded-models`) on the list entry when a
future version supplies it, and otherwise reads the file named by the entry's `path`, parses the JSON,
and copies only that one key. Every other key, including token fields, is discarded and never logged or
sent to the browser. The path is resolved and confirmed to sit under the CLIProxyAPI auth directory
before being opened, so a hostile or malformed `path` cannot make codex-lb read arbitrary files.

A live auth file may already carry an `excluded_models` list placed there by hand. That is data, not
configuration owned by this change: the editor simply displays it and lets an operator clear it.

## Normalization

Entries are trimmed, deduplicated case-insensitively keeping the first spelling, capped at 128
characters each and 32 entries total, and rejected when they contain a newline, NUL, or comma. The
comma matters for a specific reason: CLIProxyAPI keeps this list as a comma-joined attribute and
splits it on `,` at routing time, so a comma inside one pattern would corrupt it into two patterns
that match nothing. Order is
preserved so the list an operator sees matches the list they built. Normalization runs on both the
write path and the read path so a hand-edited file cannot produce a list the UI could not have made.
