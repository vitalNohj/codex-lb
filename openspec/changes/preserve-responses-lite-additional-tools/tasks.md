# Tasks

- [x] 1. Update `_normalize_responses_input_instructions` to early-return when `input` contains `additional_tools`, and to pass through non-message `system`/`developer` items during hoist
- [x] 2. Add unit regression tests for Lite prefix preservation on `ResponsesRequest` and `ResponsesCompactRequest`, plus typeless system hoist still works
- [x] 3. Run `uv run pytest tests/unit/test_openai_requests.py -q` and `openspec validate preserve-responses-lite-additional-tools --strict`
