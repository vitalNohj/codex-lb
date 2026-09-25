import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { RESIZABLE_PANEL_TARGET_ATTR, ResizablePanel } from "@/components/resizable-panel";

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

  it("previews the clamped height during a drag and commits it once on release", () => {
    const onHeightChange = renderPanel(300);
    const grip = screen.getByRole("separator", { name: "Resize list" });
    const frame = screen.getByTestId("resizable-panel-frame");
    vi.spyOn(frame, "getBoundingClientRect").mockReturnValue({ height: 300 } as DOMRect);
    Object.defineProperty(grip, "setPointerCapture", { value: vi.fn() });
    Object.defineProperty(grip, "releasePointerCapture", { value: vi.fn() });
    Object.defineProperty(grip, "hasPointerCapture", { value: () => true });

    fireEvent.pointerDown(grip, { button: 0, pointerId: 1, clientY: 10 });
    fireEvent.pointerMove(grip, { pointerId: 1, clientY: 110 });
    expect(frame.style.getPropertyValue("--panel-height")).toBe("400px");
    expect(onHeightChange).not.toHaveBeenCalled();

    fireEvent.pointerMove(grip, { pointerId: 1, clientY: 2000 });
    expect(frame.style.getPropertyValue("--panel-height")).toBe("800px");

    fireEvent.pointerUp(grip, { pointerId: 1 });
    expect(onHeightChange).toHaveBeenCalledTimes(1);
    expect(onHeightChange).toHaveBeenCalledWith(800);

    fireEvent.pointerMove(grip, { pointerId: 1, clientY: 50 });
    expect(onHeightChange).toHaveBeenCalledTimes(1);
  });

  it("commits the in-flight height when pointer capture is lost", () => {
    const onHeightChange = renderPanel(300);
    const grip = screen.getByRole("separator", { name: "Resize list" });
    vi.spyOn(screen.getByTestId("resizable-panel-frame"), "getBoundingClientRect").mockReturnValue({
      height: 300,
    } as DOMRect);
    Object.defineProperty(grip, "setPointerCapture", { value: vi.fn() });
    Object.defineProperty(grip, "releasePointerCapture", { value: vi.fn() });
    Object.defineProperty(grip, "hasPointerCapture", { value: () => false });

    fireEvent.pointerDown(grip, { button: 0, pointerId: 1, clientY: 10 });
    fireEvent.pointerMove(grip, { pointerId: 1, clientY: 60 });
    fireEvent.lostPointerCapture(grip, { pointerId: 1 });

    expect(onHeightChange).toHaveBeenCalledTimes(1);
    expect(onHeightChange).toHaveBeenCalledWith(350);
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

  it("measures the tagged target rather than the frame when a child marks one", () => {
    const onHeightChange = vi.fn();
    render(
      <ResizablePanel height={null} onHeightChange={onHeightChange} minHeight={100} maxHeight={800} label="Resize list">
        <div style={{ border: "1px solid" }}>
          <div {...{ [RESIZABLE_PANEL_TARGET_ATTR]: "" }} data-testid="target" />
        </div>
      </ResizablePanel>,
    );
    vi.spyOn(screen.getByTestId("resizable-panel-frame"), "getBoundingClientRect").mockReturnValue({ height: 340 } as DOMRect);
    vi.spyOn(screen.getByTestId("target"), "getBoundingClientRect").mockReturnValue({ height: 300 } as DOMRect);

    fireEvent.keyDown(screen.getByRole("separator", { name: "Resize list" }), { key: "ArrowDown" });

    expect(onHeightChange).toHaveBeenCalledWith(332);
  });
});
