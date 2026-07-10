## ADDED Requirements

### Requirement: Coerce non-text chat tool message content arrays

The service MUST map `/v1/chat/completions` `role=tool` messages whose `content` is a non-empty array with no extractable string `text` parts into a Responses `function_call_output` whose `output` is the compact JSON serialization of that array. The service MUST NOT reject the request solely because the tool content array contains only non-text parts (for example `image_url`) or text parts that omit the `text` field. When the array contains one or more parts with a string `text` field (including empty string), the service MUST join those text values with no delimiter and MUST NOT JSON-serialize the array. Empty array content `[]` MUST still produce `output` equal to `""`. Tool messages with `content: null` or non-string/non-array content MUST still be rejected.

#### Scenario: Image-only tool content array accepted

- **WHEN** a client sends a `role=tool` message whose `content` is `[{"type":"image_url","image_url":{"url":"data:image/png;base64,abc"}}]`
- **THEN** the mapped Responses `function_call_output.output` MUST equal the compact JSON serialization of that content array

#### Scenario: Empty text part produces empty output

- **WHEN** a client sends a `role=tool` message whose `content` is `[{"type":"text","text":""}]`
- **THEN** the mapped Responses `function_call_output.output` MUST equal `""`

#### Scenario: Malformed text part falls back to JSON

- **WHEN** a client sends a `role=tool` message whose `content` is `[{"type":"text"}]` (no `text` field)
- **THEN** the mapped Responses `function_call_output.output` MUST equal the compact JSON serialization of that content array
