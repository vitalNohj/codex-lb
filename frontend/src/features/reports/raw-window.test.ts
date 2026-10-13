import { describe, expect, it } from "vitest";

import { isBeforeRawWindow, prunedRangeBounds } from "./raw-window";

describe("isBeforeRawWindow", () => {
  it("flags only days strictly before the raw window start", () => {
    expect(isBeforeRawWindow("2026-09-12", "2026-09-13")).toBe(true);
    expect(isBeforeRawWindow("2026-09-13", "2026-09-13")).toBe(false);
    expect(isBeforeRawWindow("2026-09-12", null)).toBe(false);
  });
});

describe("prunedRangeBounds", () => {
  it("returns the MM-DD span of the pruned days", () => {
    expect(
      prunedRangeBounds(["2026-09-10", "2026-09-11", "2026-09-12", "2026-09-13"], "2026-09-12"),
    ).toEqual({ x1: "09-10", x2: "09-11" });
  });

  it("returns null when the range stays inside the raw window", () => {
    expect(prunedRangeBounds(["2026-09-12", "2026-09-13"], "2026-09-12")).toBeNull();
    expect(prunedRangeBounds(["2026-09-12"], null)).toBeNull();
  });
});
