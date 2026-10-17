"""CLIProxyAPI credential inventory, field edits, sign-in, refresh, and delete.

Dispatch stays on the existing Claude sidecar path. Prefixes edited here are
stored in codex-lb and are not used to route requests yet. Session stickiness
is the global CLIProxyAPI ``routing.session-affinity`` switch, not a field on
each account.
"""
