# Model Pricing

Requests routed through the OpenRouter, OrcaRouter, and CLIProxyAPI integrations
get a cost in the request log by resolving the model against the provider's own
published catalog. This page covers what the numbers mean and how to maintain
them.

Ollama and OmniRoute do not participate. Their request-log cost stays `--`:
local inference has no published external rate, and OmniRoute's routing does not
identify a catalog model to price.

## Two kinds of cost

The request log distinguishes what was **billed** from what the request **lists
at**. They are not the same number and are never merged.

| Cost source | Meaning |
|---|---|
| Upstream billed | The integration reported debiting this amount. This is your actual spend. |
| Catalog calculated | The catalog's published token rates multiplied by the recorded token usage. Exact arithmetic, but list price. |

A billed amount always wins and is stored exactly as reported. It folds in
tiered pricing, peak/off-peak multipliers, cache ratios, and minimum-quota
rounding that cannot be reproduced from published rates, so a calculated figure
never overwrites it.

A calculated figure is recorded only when the upstream reported nothing. Hover
the cost in the request log to see which kind you are looking at.

Calculated costs are included in cost totals.

## Reading the cost column

| Display | Meaning |
|---|---|
| A figure | A cost was recorded. Hover to see whether it is billed or list price. |
| `!!` | This model should have a published token price and does not. Hover for the reason. |
| `--` | No cost is expected: an excluded integration, no reported token usage, or a model billed per request rather than per token. |

`!!` has two causes, both shown in the tooltip:

- **Not found** - no catalog lists a price for this model id yet.
- **Ambiguous** - the name matches more than one catalog entry at different
  prices, so no price was recorded rather than guessing wrong.

An unpriced model is still served and still counted normally. Allow lists and
quotas are unaffected.

## How a price is found

Resolution stops at the first match:

1. An explicit alias you configured under **Settings → Routing**.
2. A routing prefix you configured, when that prefix is marked to strip. This is
   what maps an id like `cc/claude-fable-5` to the vendor's real catalog entry.
3. An exact catalog id.
4. The same id with `.` or `_` written as `-`.
5. A bare name matched to exactly one vendor-qualified catalog id.

The serving provider's own catalog is checked before OpenRouter's, because
providers list overlapping model ids at different prices.

OpenRouter is used as a **pricing reference only**. A model's presence in or
absence from OpenRouter never affects whether codex-lb considers it available or
routes to it.

If a step finds more than one plausible match, no price is recorded. The
competing candidates are saved so you can see them in the maintenance report.

## Lookup behavior

The first request for a model id you have not routed before records no cost and
schedules one background lookup. Requests never wait on it. From the second
request onward the price comes from local storage with no network work.

A model that could not be priced is retried on a widening schedule (5 minutes,
30 minutes, 2 hours, 6 hours, then daily) rather than on every request, so an
unknown model cannot generate lookup traffic.

## Refreshing prices

Prices are not polled. Refresh them deliberately:

```bash
codex-lb model-prices refresh
```

One pass, safe to re-run. It fetches each catalog once, applies changed rates,
and reports what it found:

```
External model price maintenance
- Records examined: 42
- Rates updated: 2
- Newly resolved: 1
- Unchanged: 38
- Preserved after a source failure: 0
- Still unresolved: 1
- Ambiguous: 0
```

Run it after a provider announces a price change, or when you see `!!` on a model
you expect to be priced.

Two outcomes are worth knowing:

- If a catalog cannot be reached, records that depend on it keep their existing
  rates. A network failure is never treated as a price change.
- If a catalog is reachable and no longer lists a model, that model becomes
  unresolved. Continuing to report its old rate would show a price no live
  listing supports.

CLIProxyAPI publishes no rates of its own, by design. That is not a fetch
failure: it is never reported as an unavailable catalog, and its records are
judged against the OpenRouter pricing reference alone, so one that is genuinely
no longer listed becomes unresolved instead of keeping a stale rate.

## Notes

- Cached input tokens are priced at the full input rate. Not every catalog
  publishes a cache-read rate, and codex-lb does not assume a discount it cannot
  cite.
- A free model records a real `$0.00`. Zero is a published price, not a missing
  one.
- Rows written before this feature shipped have no recorded provenance. They are
  shown as-is and are not reclassified.

---

*Spec: [external-model-pricing](https://github.com/Soju06/codex-lb/tree/main/openspec/specs/external-model-pricing)*
