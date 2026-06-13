## 1. Advertise the sidecar context window

- [x] 1.1 Add a helper that builds the capability/context fields (`context_length`, `contextLength`, `capabilities.context_length`) for sidecar models using the standard Claude 200000 window.
- [x] 1.2 Merge those fields into the Claude sidecar entries when building `GET /v1/models`.

## 2. Cover the regression

- [x] 2.1 Extend the sidecar model-list integration test to assert the sidecar entry exposes `context_length=200000` (and the camelCase / capabilities mirrors).

## 3. Validate the change

- [ ] 3.1 Run focused OpenSpec validation and the targeted `/v1/models` + sidecar routing tests.
