## Why

When an image request for an OmniRoute sidecar model arrives on the Responses
endpoints (`POST /v1/responses`, `POST /backend-api/codex/responses`), the
Responses→chat-completions translation flattens every input item to text only
and silently drops `input_image` (and `image_url`) content parts. The forwarded
OmniRoute request therefore contains a plain-string `content` with no image, so
the upstream model never sees the picture.

This was verified against live traffic: the same image sent to the Claude model
through OmniRoute works directly and through codex-lb's `/v1/chat/completions`
path (the forwarded OmniRoute request carries the `image_url` data URL), but the
`/v1/responses` path forwards `content` as a bare string and the model replies
"I don't see an image in our conversation." Codex-lb's extra translation layer
is the only difference, and the defect is isolated to
`responses_to_omniroute_chat_request`.

## What Changes

- Preserve user image content when translating a Responses sidecar request into
  the OmniRoute chat-completions request: `input_image`/`image_url` parts MUST be
  emitted as OpenAI chat `image_url` content parts instead of being dropped.
- Keep text-only content collapsed to a plain string so simple turns stay
  compact and existing behavior is unchanged.

## Non-goals

- Do not change the chat-completions sidecar path (it already preserves images).
- Do not add image handling to providers other than OmniRoute in this change.
- Do not change image size limits, file uploads, or `input_file` handling.

## Capabilities

### Modified Capabilities

- `responses-api-compat`: the Responses→chat-completions translation for
  OmniRoute sidecar requests preserves multimodal image content.

## Impact

- `app/modules/proxy/omniroute_responses_dispatch.py`
  (`responses_to_omniroute_chat_request` content translation).
- Unit tests in `tests/unit/test_omniroute_responses_dispatch.py`.
