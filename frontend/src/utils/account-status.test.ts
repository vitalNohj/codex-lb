import { describe, expect, it } from "vitest";

import { cliproxyAuthBadgeStatus } from "@/utils/account-status";

describe("cliproxyAuthBadgeStatus", () => {
  it("keeps re-auth ahead of quota exhaustion and pause", () => {
    expect(cliproxyAuthBadgeStatus({ status: "reauth_required", quotaExceeded: true }, "active")).toBe("reauth");
    expect(cliproxyAuthBadgeStatus({ status: "reauth_required", paused: true }, "active")).toBe("reauth");
  });

  it("shows a pause before quota exhaustion", () => {
    expect(cliproxyAuthBadgeStatus({ status: "active", paused: true, quotaExceeded: true }, "active")).toBe("paused");
  });

  it("shows quota exhaustion over the reported status", () => {
    expect(cliproxyAuthBadgeStatus({ status: "active", quotaExceeded: true }, "active")).toBe("exceeded");
  });

  it("falls back to the reported or account status", () => {
    expect(cliproxyAuthBadgeStatus({ status: "rate_limited" }, "active")).toBe("limited");
    expect(cliproxyAuthBadgeStatus({ status: null }, "paused")).toBe("paused");
  });
});
