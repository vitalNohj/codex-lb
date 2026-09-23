export function ForkMark({ children = "fork" }: { children?: string }) {
  return (
    <span className="shrink-0 rounded-md border border-border/70 bg-muted/50 px-1.5 py-0.5 text-[10px] font-medium leading-none tracking-wide text-muted-foreground">
      {children}
    </span>
  );
}
