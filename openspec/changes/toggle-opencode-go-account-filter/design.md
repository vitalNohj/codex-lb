## Overview

OpenCode Go already appears on the dashboard as one synthetic account (`provider: "opencode_go"`, `account_id: "opencode-go-sidecar"`). The Accounts filter hides an account only when `accountTypeKey` returns a key in `accountTypeVisibility`. Unknown providers return `"other"`, and `"other"` is always shown.

## Decision

Add `opencode_go` to `AccountTypeKey` and `ACCOUNT_TYPE_KEYS`. Map `provider === "opencode_go"` to that key. Label the button `OpenCode Go`.

Place the button after OrcaRouter, and after OmniRoute when that capability is enabled, and before OpenAI-compat. That follows `SIDECAR_PROVIDER_ORDER` for the keys this filter already shows. OmniRoute stays off the filter while `OMNIROUTE_ENABLED` is false.

Default the key to `true`. Hydration starts from that default and overlays only stored booleans, so a preference written before this key keeps every other toggle and shows OpenCode Go until the operator hides it.

No server change. The summary builder already emits the account.
