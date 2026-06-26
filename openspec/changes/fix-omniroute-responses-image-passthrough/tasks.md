## 1. OpenSpec artifacts

- [x] 1.1 Write proposal and delta spec for OmniRoute Responses image pass-through.
- [x] 1.2 Validate with `openspec validate fix-omniroute-responses-image-passthrough --strict`.

## 2. Implementation

- [x] 2.1 Update `responses_to_omniroute_chat_request` content translation to preserve `input_image`/`image_url` parts as OpenAI chat `image_url` parts.
- [x] 2.2 Keep text-only content collapsed to a plain string.

## 3. Tests

- [x] 3.1 Unit test: `input_image` (string URL) is preserved as an `image_url` chat part.
- [x] 3.2 Unit test: `image_url` object with `detail` is preserved including `detail`.
- [x] 3.3 Existing text-only translation behavior unchanged.

## 4. Verification

- [x] 4.1 Run `uv run pytest tests/unit/test_omniroute_responses_dispatch.py`.
- [x] 4.2 Run `uv run ruff check` on changed files.
- [x] 4.3 Run `openspec validate fix-omniroute-responses-image-passthrough --strict`.
