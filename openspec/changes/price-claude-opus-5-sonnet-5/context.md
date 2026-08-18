## Purpose

Fill Claude sidecar Request Logs `--` cost for Opus 5 / Sonnet 5. Cost is estimated Anthropic list price from token usage, same as Fable 5.

## Non-goals

- Per-client cost logic
- Changing how CLIProxyAPI usage is captured
- Invoice-accurate Anthropic billing (OAuth is flat-rate)

## Example

Live 7-day store before this change:

- `cc/claude-opus-5`: 16534 rows, 16534 NULL `cost_usd`, 16410 with tokens
- `cc/claude-fable-5`: 777 rows, 773 with cost
- Cursor key on Opus 5: 134 rows, all NULL cost (Cursor is not special)

After: `add_log` for `cc/claude-opus-5` with 1M input + 1M output stores `$30.00` (5 + 25). Cached tokens use the 10% cache-hit rate. Folded usage rollups gain those dollars via a cost-only delta; the fold watermark stays put.

## Related

- `openspec/changes/fix-claude-sidecar-usage-and-cost` added the original Claude table
- Anthropic pricing: https://platform.claude.com/docs/en/about-claude/pricing
