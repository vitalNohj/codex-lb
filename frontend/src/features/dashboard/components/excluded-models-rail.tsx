import { Ban } from "lucide-react";
import { useLayoutEffect, useRef } from "react";

import { excludedModelChips } from "@/features/settings/lib/excluded-model-families";
import { cn } from "@/lib/utils";

export type ExcludedModelsRailProps = {
  excludedModels: readonly string[];
  className?: string;
};

// Within this many pixels of an edge counts as at the edge, which absorbs the
// fractional scroll positions that zoomed and high-DPI screens report.
const EDGE_TOLERANCE_PX = 1;

/**
 * A single-line, read-only list of an account's excluded models.
 *
 * The chips never wrap. When they outgrow the row, the list scrolls sideways
 * with its scrollbar hidden, and whichever edge hides chips fades out, so the
 * cut reads as "more this way". The "Excluded" caption collapses to its icon
 * when the row is narrow, leaving the room to the chips. Editing lives on the
 * details page and in Settings, so scrolling is the only interaction here.
 */
export function ExcludedModelsRail({ excludedModels, className }: ExcludedModelsRailProps) {
  const scrollerRef = useRef<HTMLDivElement>(null);
  const chips = excludedModelChips(excludedModels);
  const hasChips = chips.length > 0;

  // Scroll state goes straight to data attributes instead of React state, so
  // scrolling the list never re-renders the card.
  useLayoutEffect(() => {
    const scroller = scrollerRef.current;
    if (!scroller) return;
    const sync = () => {
      const maxScroll = scroller.scrollWidth - scroller.clientWidth;
      const scrollable = maxScroll > EDGE_TOLERANCE_PX;
      const scrolled = scroller.scrollLeft;
      scroller.toggleAttribute("data-overflow-start", scrollable && scrolled > EDGE_TOLERANCE_PX);
      scroller.toggleAttribute("data-overflow-end", scrollable && scrolled < maxScroll - EDGE_TOLERANCE_PX);
      // A scroll container must be reachable by keyboard, but only while it
      // actually scrolls; otherwise it would be a dead tab stop.
      if (scrollable) {
        scroller.setAttribute("tabindex", "0");
      } else {
        scroller.removeAttribute("tabindex");
      }
    };
    sync();
    scroller.addEventListener("scroll", sync, { passive: true });
    // Watch the chip list as well as the scroller: a late web-font swap or a
    // new pattern changes the content width without resizing the scroller.
    const observer = new ResizeObserver(sync);
    observer.observe(scroller);
    if (scroller.firstElementChild) observer.observe(scroller.firstElementChild);
    return () => {
      scroller.removeEventListener("scroll", sync);
      observer.disconnect();
    };
  }, [hasChips]);

  if (!hasChips) return null;

  return (
    // The outer box takes the row's leftover width and is the size container
    // the caption measures; the inner box shrink-wraps the chips, so the
    // tooltip and focus ring cover the chips rather than the empty space.
    <div className={cn("@container min-w-0 flex-1", className)}>
      <div
        title={`Excluded models: ${chips.map((chip) => chip.label).join(", ")}`}
        className="flex w-fit max-w-full items-center gap-2 rounded-md has-[:focus-visible]:ring-[3px] has-[:focus-visible]:ring-ring/50"
      >
        <span
          aria-hidden="true"
          className="flex shrink-0 items-center gap-1 text-[11px] font-medium text-muted-foreground"
        >
          <Ban className="size-3" />
          <span className="hidden @min-[12rem]:inline">Excluded</span>
        </span>
        <div
          ref={scrollerRef}
          role="group"
          aria-label="Excluded models"
          className={cn(
            "min-w-0 overflow-x-auto overscroll-x-contain outline-none",
            "[scrollbar-width:none] [&::-webkit-scrollbar]:hidden",
            "data-[overflow-start]:mask-l-from-[calc(100%-1.25rem)]",
            "data-[overflow-end]:mask-r-from-[calc(100%-1.25rem)]",
          )}
        >
          <ul role="list" className="flex w-max items-center gap-1">
            {chips.map((chip) => (
              <li
                key={chip.key}
                title={chip.patterns.join(", ")}
                className={cn(
                  "max-w-40 shrink-0 truncate rounded-md border border-border/70 bg-muted/50 px-1.5 text-[11px] leading-[18px] font-medium text-foreground/80",
                  chip.custom && "font-mono font-normal",
                )}
              >
                {chip.label}
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
}
