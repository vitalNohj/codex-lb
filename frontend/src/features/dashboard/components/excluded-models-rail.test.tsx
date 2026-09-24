import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ExcludedModelsRail } from "@/features/dashboard/components/excluded-models-rail";

/** jsdom has no layout engine, so hand the scroller the sizes a browser would measure. */
function setScrollerSize(scroller: HTMLElement, clientWidth: number, scrollWidth: number) {
  Object.defineProperty(scroller, "clientWidth", { configurable: true, value: clientWidth });
  Object.defineProperty(scroller, "scrollWidth", { configurable: true, value: scrollWidth });
}

function scrollTo(scroller: HTMLElement, left: number) {
  scroller.scrollLeft = left;
  fireEvent.scroll(scroller);
}

describe("ExcludedModelsRail", () => {
  it("renders nothing when no pattern would show a chip", () => {
    const { container, rerender } = render(<ExcludedModelsRail excludedModels={[]} />);
    expect(container).toBeEmptyDOMElement();

    rerender(<ExcludedModelsRail excludedModels={["", "  "]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("shows one chip per family or custom pattern, each naming its patterns on hover", () => {
    render(<ExcludedModelsRail excludedModels={["claude-fable-*", "claude-opus-4-*", "claude-fable"]} />);

    const group = screen.getByRole("group", { name: "Excluded models" });
    const chips = within(group).getAllByRole("listitem");
    expect(chips.map((chip) => chip.textContent)).toEqual(["Fable", "claude-opus-4-*"]);
    expect(chips[0]).toHaveAttribute("title", "claude-fable-*, claude-fable");
    expect(chips[1]).toHaveAttribute("title", "claude-opus-4-*");
    expect(screen.getByTitle("Excluded models: Fable, claude-opus-4-*")).toContainElement(group);
  });

  it("fades only the edges that hide chips, and is a tab stop only while it scrolls", () => {
    render(<ExcludedModelsRail excludedModels={["claude-fable-*", "claude-opus-4-*", "claude-x-1"]} />);
    const scroller = screen.getByRole("group", { name: "Excluded models" });

    // Everything fits, so there is nothing to fade and nothing to scroll to.
    expect(scroller).not.toHaveAttribute("data-overflow-start");
    expect(scroller).not.toHaveAttribute("data-overflow-end");
    expect(scroller).not.toHaveAttribute("tabindex");

    setScrollerSize(scroller, 100, 300);
    scrollTo(scroller, 0);
    expect(scroller).not.toHaveAttribute("data-overflow-start");
    expect(scroller).toHaveAttribute("data-overflow-end");
    expect(scroller).toHaveAttribute("tabindex", "0");

    scrollTo(scroller, 100);
    expect(scroller).toHaveAttribute("data-overflow-start");
    expect(scroller).toHaveAttribute("data-overflow-end");

    // A fractional offset a pixel short of the end still counts as the end.
    scrollTo(scroller, 199.5);
    expect(scroller).toHaveAttribute("data-overflow-start");
    expect(scroller).not.toHaveAttribute("data-overflow-end");

    // Once the row is wide enough again, the fades and the tab stop go away.
    setScrollerSize(scroller, 300, 300);
    scrollTo(scroller, 0);
    expect(scroller).not.toHaveAttribute("data-overflow-start");
    expect(scroller).not.toHaveAttribute("data-overflow-end");
    expect(scroller).not.toHaveAttribute("tabindex");
  });
});
