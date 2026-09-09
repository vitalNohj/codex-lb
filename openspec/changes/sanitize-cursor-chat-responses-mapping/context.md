# Context

Live Cursor `POST /v1/chat/completions` for `gpt-6-astra` (alias `codex/gpt-6-astra`)
returned `usage_limit_reached` before any tokens. Failover chose `failover_next`,
then re-required the exhausted Plus seat as dispatch owner because the mapped
Responses body was not an account-neutral fresh replay.

`cursor_chat_compat.py` did not participate. That layer only rewrites usage and
context-length compaction. HTTP chat completions always set
`openai_cache_affinity=True` and map through `ChatCompletionsRequest.to_responses_request()`.
`request_stage=first_turn` on that path means "no previous_response_id / turn-state",
not "no Composer tool history".

Classification of mapped bodies:

| Shape | Account-neutral? |
| --- | --- |
| User + nested OpenAI tools + `tool_choice: "auto"` | yes |
| Same + `frequency_penalty` / `seed` / `logit_bias` | no (extra keys) |
| `tool_choice: {"type":"auto"}` | no |
| Assistant `content: ""` + paired `tool_calls` | no (blank `output_text`) |
| Assistant `content: null` + paired `tool_calls` | yes |
| Flat `{name, input_schema}` tools | no (`type` missing, `input_schema` extra) |
| Function tool with `container_id` | no (correct fail-closed) |
| Unpaired trailing `tool_calls` | no (correct fail-closed) |

Sidecar `sidecar_tool_mapper.py` already normalizes the Cursor-native tool
grammar. Native Codex mapping did not.

Do not put this in `cursor_chat_compat.py`. Do not mark all Cursor payloads
account-neutral. Do not drop `container_id` or unpaired tool calls.
