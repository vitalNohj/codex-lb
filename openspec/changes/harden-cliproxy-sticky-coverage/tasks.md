## 1. Session identity

- [x] 1.1 Read session headers and body session ids, and derive a content key with the Codex `_derive_prompt_cache_key` recipe; keep content that cannot be hashed unpinned.
- [x] 1.2 Forward `prompt_cache_key` through `responses_to_chat_request` and derive one before translation when it is absent; rank a derived key below session headers.

## 2. Pin stability

- [x] 2.1 Keep the warm pin through a transient 429/401/403 with a cooldown and a fallback pin; move the pin on quota exhaustion or when the failing request created it.
- [x] 2.2 Claim pins with compare-and-set so concurrent first turns share one credential.
- [x] 2.3 Purge expired CLIProxyAPI pins in the sticky cleanup loop.
- [x] 2.4 Score unmeasured credentials neutrally and warn when a model has no prefixed credential.

## 3. Observability

- [x] 3.1 Count and log route outcomes by key source; chart them on the Helm Grafana overview.

## 4. Validation

- [x] 4.1 Regression tests for every finding in `tests/unit/test_cliproxy_sticky_coverage.py`.
- [x] 4.2 End-to-end lab against a real CLIProxyAPI v8 binary and a per-key cache-simulating upstream: scenarios 3, 4a, 4b, 7 and 9 stay on one credential; 1, 2, 5 and 8 do not regress.
