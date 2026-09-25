import { GripHorizontal } from "lucide-react";
import { useRef, type CSSProperties, type KeyboardEvent, type PointerEvent, type ReactNode } from "react";

import { cn } from "@/lib/utils";

export type ResizablePanelProps = {
  /** Current height in px, or `null` to use the child's own default height. */
  height: number | null;
  onHeightChange: (height: number | null) => void;
  minHeight: number;
  maxHeight?: number;
  /** Accessible name for the grip, e.g. "Resize account list". */
  label: string;
  className?: string;
  children: ReactNode;
};

const KEYBOARD_STEP_PX = 32;

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

/** Marks the element whose height `--panel-height` actually controls. */
export const RESIZABLE_PANEL_TARGET_ATTR = "data-resizable-panel-target";

/**
 * Vertically resizable container with a drag rail along its bottom edge.
 *
 * The panel itself renders no scroll region: the child owns overflow and reads
 * the resolved height through a CSS variable (`--panel-height`) so it can keep
 * its own default when the operator has not resized yet. Double-clicking the
 * rail restores that default.
 *
 * The drag baseline must be the box the variable sizes, not the frame: a child
 * may wrap its scroller in borders or a horizontal scrollbar, and measuring
 * those would make the first drag pixel jump. Children tag that box with
 * {@link RESIZABLE_PANEL_TARGET_ATTR}; without the tag the frame is measured.
 */
export function ResizablePanel({
  height,
  onHeightChange,
  minHeight,
  maxHeight = Number.POSITIVE_INFINITY,
  label,
  className,
  children,
}: ResizablePanelProps) {
  const frameRef = useRef<HTMLDivElement>(null);
  const dragRef = useRef<{ pointerId: number; startY: number; startHeight: number } | null>(null);

  const measuredHeight = () => {
    const frame = frameRef.current;
    if (!frame) {
      return minHeight;
    }
    const target = frame.querySelector<HTMLElement>(`[${RESIZABLE_PANEL_TARGET_ATTR}]`) ?? frame;
    return target.getBoundingClientRect().height;
  };

  const onPointerDown = (event: PointerEvent<HTMLButtonElement>) => {
    if (event.button !== 0) {
      return;
    }
    event.preventDefault();
    dragRef.current = { pointerId: event.pointerId, startY: event.clientY, startHeight: measuredHeight() };
    event.currentTarget.setPointerCapture(event.pointerId);
  };

  const onPointerMove = (event: PointerEvent<HTMLButtonElement>) => {
    const drag = dragRef.current;
    if (!drag || drag.pointerId !== event.pointerId) {
      return;
    }
    onHeightChange(Math.round(clamp(drag.startHeight + (event.clientY - drag.startY), minHeight, maxHeight)));
  };

  const onPointerUp = (event: PointerEvent<HTMLButtonElement>) => {
    const drag = dragRef.current;
    if (!drag || drag.pointerId !== event.pointerId) {
      return;
    }
    dragRef.current = null;
    event.currentTarget.releasePointerCapture(event.pointerId);
  };

  const onKeyDown = (event: KeyboardEvent<HTMLButtonElement>) => {
    const delta =
      event.key === "ArrowDown" ? KEYBOARD_STEP_PX : event.key === "ArrowUp" ? -KEYBOARD_STEP_PX : null;
    if (delta === null) {
      if (event.key === "Home" || event.key === "Escape") {
        event.preventDefault();
        onHeightChange(null);
      }
      return;
    }
    event.preventDefault();
    onHeightChange(Math.round(clamp(measuredHeight() + delta, minHeight, maxHeight)));
  };

  const style: CSSProperties | undefined = height === null ? undefined : ({ "--panel-height": `${height}px` } as CSSProperties);

  return (
    <div className={cn("flex flex-col", className)}>
      <div ref={frameRef} data-testid="resizable-panel-frame" style={style}>
        {children}
      </div>
      {/*
        Full-width rail: a small corner grip is easy to miss, and the rail
        doubles as the visible bottom edge of the scroll region.
      */}
      <button
        type="button"
        role="separator"
        aria-orientation="horizontal"
        aria-label={label}
        aria-valuenow={height ?? undefined}
        aria-valuemin={minHeight}
        aria-valuemax={Number.isFinite(maxHeight) ? maxHeight : undefined}
        title={`${label} (drag; double-click to reset)`}
        className="group mt-1.5 flex h-4 w-full cursor-ns-resize touch-none items-center justify-center rounded-md text-muted-foreground/70 transition-colors hover:bg-accent/60 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
        onDoubleClick={() => onHeightChange(null)}
        onKeyDown={onKeyDown}
      >
        <span className="flex items-center gap-2">
          <span className="h-px w-10 bg-border transition-colors group-hover:bg-foreground/30" aria-hidden="true" />
          <GripHorizontal className="h-3.5 w-3.5" aria-hidden="true" />
          <span className="h-px w-10 bg-border transition-colors group-hover:bg-foreground/30" aria-hidden="true" />
        </span>
      </button>
    </div>
  );
}
