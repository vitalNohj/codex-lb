// Per-request measures (TTFT, TPS, queue wait, user agent) only exist for the
// raw request-log window. Days before it are not "zero", they are unknown, so
// charts plot them as gaps and shade the span instead of drawing a flat line.

export function isBeforeRawWindow(date: string, rawMetricsSince: string | null | undefined): boolean {
  return Boolean(rawMetricsSince && date < rawMetricsSince);
}

/**
 * Returns the x-axis span (the charts' MM-DD category keys) of the days that
 * precede the raw window, or null when the range stays inside it.
 *
 * @param dates Full ISO dates (YYYY-MM-DD) of the plotted days, in order.
 */
export function prunedRangeBounds(
  dates: string[],
  rawMetricsSince: string | null | undefined,
): { x1: string; x2: string } | null {
  if (!rawMetricsSince) return null;
  const pruned = dates.filter((date) => date < rawMetricsSince);
  if (pruned.length === 0) return null;
  return { x1: pruned[0].slice(5), x2: pruned[pruned.length - 1].slice(5) };
}
