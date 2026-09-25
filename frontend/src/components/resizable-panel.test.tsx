import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ResizablePanel } from "@/components/resizable-panel";

function renderPanel(height: number | null, onHeightChange = vi.fn()) {
  render(
    <ResizablePanel height={height} onHeightChange={onHeightChange} minHeight={100} maxHeight={800} label="Resize list">
      <div data-testid="child" />
    </ResizablePanel>,
  );
  return onHeightChange;
}

describe("ResizablePanel", () => {
  it("leaves the child's default height alone until resized", () => {
    renderPanel(null);

    expect(screen.getByTestId("resizable-panel-frame").style.getPropertyValue("--panel-height")).toBe("");
  });

  it("exposes a stored height through --panel-height", () => {
    renderPanel(420);

    expect(screen.getByTestId("resizable-panel-frame").style.getPropertyValue("--panel-height")).toBe("420px");
    expect(screen.getByRole("separator", { name: "Resize list" })).toHaveAttribute("aria-valuenow", "420");
  });

  it("reports a clamped height while the grip is dragged", () => {
    const onHeightChange = renderPanel(300);
    const grip = screen.getByRole("separator", { name: "Resize list" });
    vi.spyOn(screen.getByTestId("resizable-panel-frame"), "getBoundingClientRect").mockReturnValue({
      height: 300,
    } as DOMRect);
    Object.defineProperty(grip, "setPointerCapture", { value: vi.fn() });
    Object.defineProperty(grip, "releasePointerCapture", { value: vi.fn() });

    fireEvent.pointerDown(grip, { button: 0, pointerId: 1, clientY: 10 });
    fireEvent.pointerMove(grip, { pointerId: 1, clientY: 110 });
    expect(onHeightChange).toHaveBeenLastCalledWith(400);

    fireEvent.pointerMove(grip, { pointerId: 1, clientY: 2000 });
    expect(onHeightChange).toHaveBeenLastCalledWith(800);

    fireEvent.pointerUp(grip, { pointerId: 1 });
    fireEvent.pointerMove(grip, { pointerId: 1, clientY: 50 });
    expect(onHeightChange).toHaveBeenCalledTimes(2);
  });

  it("resets to the default on double-click and Home", () => {
    const onHeightChange = renderPanel(500);
    const grip = screen.getByRole("separator", { name: "Resize list" });

    fireEvent.doubleClick(grip);
    fireEvent.keyDown(grip, { key: "Home" });

    expect(onHeightChange).toHaveBeenNthCalledWith(1, null);
    expect(onHeightChange).toHaveBeenNthCalledWith(2, null);
  });

  it("steps the height with the arrow keys", () => {
    const onHeightChange = renderPanel(300);
    vi.spyOn(screen.getByTestId("resizable-panel-frame"), "getBoundingClientRect").mockReturnValue({
      height: 300,
    } as DOMRect);
    const grip = screen.getByRole("separator", { name: "Resize list" });

    fireEvent.keyDown(grip, { key: "ArrowDown" });
    fireEvent.keyDown(grip, { key: "ArrowUp" });

    expect(onHeightChange).toHaveBeenNthCalledWith(1, 332);
    expect(onHeightChange).toHaveBeenNthCalledWith(2, 268);
  });
});
