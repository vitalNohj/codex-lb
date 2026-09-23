import { GitFork } from "lucide-react";

import { cn } from "@/lib/utils";

export type ForkMarkProps = {
  children?: string;
  /** A font-size class here scales the whole tag, glyph included. */
  className?: string;
};

/**
 * The "fork" tag that follows the Codex LB++ wordmark.
 *
 * It borrows the logo tile's primary tint, so the logo, the wordmark, and the
 * tag read as one lockup. Padding, gap, corner radius, and glyph are all in
 * `em`, so a caller resizes the tag by setting only a font size.
 *
 * The label is uppercase because Geist's capitals sit exactly on the centre of
 * a `leading-none` line box, which keeps the text optically centred in the tag
 * and level with the capitals of the wordmark beside it.
 */
export function ForkMark({ children = "fork", className }: ForkMarkProps) {
  return (
    <span
      className={cn(
        "inline-flex shrink-0 items-center gap-[0.3em] rounded-[0.5em] bg-gradient-to-br from-primary/15 to-primary/5 px-[0.6em] py-[0.3em] text-[10px] font-semibold tracking-[0.08em] text-primary uppercase ring-1 ring-primary/15 ring-inset",
        className,
      )}
    >
      <GitFork aria-hidden="true" className="size-[1em] shrink-0" strokeWidth={2.5} />
      {/*
        The line height sits on the label rather than the tag, so a caller's
        font-size class cannot reset it. The negative margin cancels the
        tracking after the last letter, which would otherwise pad the right.
      */}
      <span className="-mr-[0.08em] leading-none">{children}</span>
    </span>
  );
}
