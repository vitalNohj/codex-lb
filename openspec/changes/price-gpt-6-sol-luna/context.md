## Purpose

Native request logs for `gpt-6-sol` and `gpt-6-luna` show no dollar cost because the static price table has no row. Both models already arrive as native Codex traffic. This change prices them the same way GPT-6 Astra is priced.

## Rates

Published OpenAI API list prices, fetched 2026-09-22 from the model pages. Per 1M tokens, input / cached input / output:

- `gpt-6-sol`: standard `2 / 0.20 / 10`, Fast/priority `4 / 0.40 / 20`, Flex `1 / 0.10 / 5`, long context `4 / 0.40 / 15`
- `gpt-6-luna`: standard `0.10 / 0.01 / 0.50`, Fast/priority `0.20 / 0.02 / 1.00`, Flex `0.05 / 0.005 / 0.25`, long context `0.20 / 0.02 / 0.75`

Long context starts above 272,000 input tokens. Cache writes (`$2.50` Sol, `$0.125` Luna) are documented by OpenAI and are not stored. `ModelPrice` has no cache-write field, and request logs do not record cache-write tokens.

A short Sol request of 200,000 input, 100,000 cached, and 1,000,000 output is `$10.22`. The same Luna request is `$0.511`.

## Non-goals

Subscription Codex traffic still spends plan quota. The stored `cost_usd` is the published API list price, the same estimate Astra already shows. Sidecar routing is unchanged. These ids are not prefixes or full models on CLIProxyAPI, OpenRouter, OmniRoute, or OrcaRouter.

## Ops

New inserts stay NULL until the process restarts onto this code. Historical NULL rows fill when the Alembic upgrade runs, which startup does. Do not restart the shared service until the operator says the in-flight work can stop. `downgrade()` does not clear costs.
