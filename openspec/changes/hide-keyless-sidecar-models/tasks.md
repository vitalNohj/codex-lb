## 1. Gate discovery on a usable key

- [x] 1.1 Add `openrouter_is_usable` / `orcarouter_is_usable`, matching `opencode_go_is_usable`.
- [x] 1.2 Use them for the OrcaRouter and OpenRouter blocks of `GET /v1/models` and `GET /api/models`.
- [x] 1.3 Treat an alias target owned by a keyless OrcaRouter, OpenRouter, or OpenCode Go integration as not visible when advertising aliases.

## 2. Cover the behavior

- [x] 2.1 Integration against loopback upstreams: keyless integrations and an all-keyless pool are not listed and not polled; a pool with one usable target is listed; configured keys are listed and polled (control).
