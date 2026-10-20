## 1. Read stored prefixes

- [x] 1.1 Move the path-confined auth-file read into `app/modules/claude_sidecar/auth_file.py` and reuse it for exclusions.
- [x] 1.2 Read an OAuth credential's prefix from its auth file when the listing omits it, in the quota snapshot parse and in `_stored_prefixes`.

## 2. Write only empty prefixes

- [x] 2.1 Send no fields PATCH for a credential whose prefix is already stored.

## 3. Validation

- [x] 3.1 Unit tests in `tests/unit/test_cliproxy_stored_prefix.py`: no PATCH for a stored prefix across expired-memory cycles, one PATCH then none for an empty prefix, the snapshot carries the on-disk prefix, and no read outside the auth directory (absolute path, `..` traversal, symlink).
- [x] 3.2 Opt-in real-binary test `tests/integration/test_cliproxy_stored_prefix_real_binary.py` (`CLIPROXYAPI_BIN`): the listing omits `prefix`, and CLIProxyAPI logs exactly one fields PATCH over three cycles.
