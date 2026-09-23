## 1. Dispatch

- [x] 1.1 Retry one OrcaRouter chat attempt on HTTP status >= 500 before any client byte, for both streaming and non-streaming.
- [x] 1.2 Leave HTTP 4xx and an already-started stream as a single failure with one request-log row.
- [x] 1.3 Apply that same retry to OpenRouter, NVIDIA, OpenCode Go (chat and Responses), and plus-button OpenAI-compatible endpoints.

## 2. Verification

- [x] 2.1 Cover 524-then-success, double 524, HTTP 400, streaming retry, and a started stream in tests.
- [x] 2.2 Run the sidecar dispatch tests and `openspec validate retry-orcarouter-provider-failure --strict`.
