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
| `!!` | A lookup ran for this model and found no published token price. Hover for the reason. |
| `--` | No cost is expected yet: an excluded integration, no reported token usage, a model billed per request rather than per token, or the very first request for a model whose lookup had not finished. |

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
6. The same id with a trailing `-YYYYMMDD` release stamp removed, re-checked from
   the top. `claude-sonnet-4-5-20250929` is the September release of the model
   catalogs list as `anthropic/claude-sonnet-4.5`, not a different model. Only
   that exact shape is removed, and only when the digits are a real date, so an
   id like `cohere/command-r7b-12-2024` keeps its trailing segment.

The serving provider's own catalog is checked before OpenRouter's, because
providers list overlapping model ids at different prices. When a provider's own
catalog cannot be reached, records it supplied keep its rates rather than being
re-priced from OpenRouter's.

OpenRouter is used as a **pricing reference only**. A model's presence in or
absence from OpenRouter never affects whether codex-lb considers it available or
routes to it.

If a step finds more than one plausible match, no price is recorded. The
competing candidates are saved so you can see them in the maintenance report.

## Lookup behavior

The first request for a model id you have not routed before records no cost and
schedules one background lookup. Requests never wait on it. From the second
request onward the price comes from local storage with no network work.
The lookup is claimed with a short durable lease, so separate replicas still run
one job and a worker crash becomes retryable when the lease expires.

That first row shows `--`, not `!!`. No lookup had concluded anything when it was
written, so it is not evidence that the model has no price. `!!` appears only
after a lookup has actually run and failed to find one.

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
- Now listed without a per-token price: 0
- Preserved after a source failure: 0
- Preserved while an integration is disabled: 0
- Preserved after an unreadable published price: 0
- Skipped, integration disabled: 0
- Still unresolved: 1
- Ambiguous: 0
```

A switched-off integration is listed separately. It is not consulted, so the
rates it supplied are preserved; records supplied by OpenRouter are still
refreshed as usual.

Run it after a provider announces a price change, or when you see `!!` on a model
you expect to be priced.

Two outcomes are worth knowing:

- If a catalog cannot be reached, records that depend on it keep their existing
  rates. A network failure is never treated as a price change. This covers the
  OpenRouter pricing reference too: a record that was resolved from it keeps its
  rate when the reference is unreachable, even if the serving catalog answered.
- If a catalog is reachable and no longer lists a model, that model becomes
  unresolved. Continuing to report its old rate would show a price no live
  listing supports.
- If a catalog still lists a model but publishes its price in a shape codex-lb
  cannot read, the last successfully read rate is kept and the model is retried
  later on a widening schedule. This is reported under "Preserved after an
  unreadable published price" rather than counted as unchanged, so an upstream
  schema change is visible instead of silently clearing rates. A catalog that
  publishes a no-price value (`-1`, `null`, or an empty string) is not that case:
  it is the catalog stating the model has no per-token rate, so the model settles
  as `--` and is never retried.
- If a catalog reachable in an earlier pass no longer answers, a record that was
  already settled keeps its answer, whether that answer was a rate or "not token
  priced". Both are answers a source produced, and an outage is not evidence
  against either.
- If a rate is replaced by a listing with no per-token price, the change is
  reported under "Now listed without a per-token price". Clearing a stored rate
  is never counted as unchanged.
- If an integration is switched off, it is listed under "Integrations disabled"
  and never reported as an unavailable catalog: it has not failed to answer. Its
  records are still judged against the OpenRouter pricing reference, which is a
  reachable source, but the switched-off integration's silence never counts as
  evidence against a settled record. With the reference also unreachable there is
  nothing to consult, and those records are counted under "Skipped, integration
  disabled" and left exactly as they are.
- If reading an integration's configuration fails, that is a failure rather than
  a switch-off: it is reported as an unavailable catalog so a transient settings
  or database problem is never mistaken for an integration you turned off.

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
- A participating request whose price is unknown reports no savings figure. Its
  actual cost is unknown rather than zero, so counting the full reference as
  money saved would invent a number.

---

*Spec: [external-model-pricing](https://github.com/Soju06/codex-lb/tree/main/openspec/specs/external-model-pricing)*
