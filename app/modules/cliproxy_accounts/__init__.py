"""CLIProxyAPI credential inventory, field edits, and config file management.

Dispatch stays on the existing Claude sidecar path. Prefixes edited here are
stored in codex-lb and are not used to route requests yet. The config editor
reads and replaces config.yaml only after an operator confirms a write.
"""
