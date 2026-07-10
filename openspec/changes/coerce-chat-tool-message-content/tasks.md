## 1. Coercion

- [x] 1.1 Update `_convert_tool_message` so non-text / empty-text tool content arrays serialize or join like Responses `_normalize_tool_output_value`
- [x] 1.2 Keep null and non-string/non-array tool content rejected

## 2. Tests

- [x] 2.1 Replace reject-on-malformed-text-parts test with JSON-fallback assertion
- [x] 2.2 Add coverage for image-only and empty-text tool content arrays
