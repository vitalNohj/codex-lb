import { describe, expect, it } from "vitest";

import { excludedModelChips, excludedModelLabels } from "@/features/settings/lib/excluded-model-families";

describe("excludedModelChips", () => {
  it("folds a family's patterns into one chip and keeps custom patterns raw", () => {
    expect(excludedModelChips(["claude-fable-*", "claude-opus-4-*", "claude-fable"])).toEqual([
      { key: "family:fable", label: "Fable", patterns: ["claude-fable-*", "claude-fable"], custom: false },
      { key: "pattern:claude-opus-4-*", label: "claude-opus-4-*", patterns: ["claude-opus-4-*"], custom: true },
    ]);
  });

  it("drops blank patterns and merges patterns that differ only in whitespace", () => {
    expect(excludedModelChips(["", "  ", " claude-opus-4-*", "claude-opus-4-* ", " claude-haiku-* "])).toEqual([
      { key: "pattern:claude-opus-4-*", label: "claude-opus-4-*", patterns: ["claude-opus-4-*"], custom: true },
      { key: "family:haiku", label: "Haiku", patterns: ["claude-haiku-*"], custom: false },
    ]);
  });

  it("returns no chips for an empty list", () => {
    expect(excludedModelChips([])).toEqual([]);
  });
});

describe("excludedModelLabels", () => {
  it("returns one label per chip, in list order", () => {
    expect(excludedModelLabels(["claude-haiku-*", "claude-fable-*", "claude-haiku", "claude-x-1"])).toEqual([
      "Haiku",
      "Fable",
      "claude-x-1",
    ]);
  });
});
