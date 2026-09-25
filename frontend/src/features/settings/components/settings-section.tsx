import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

export type SettingsSectionProps = {
  id?: string;
  className?: string;
  "aria-label"?: string;
  children: ReactNode;
};

/**
 * Card shell shared by every Settings section so spacing, radius, and surface
 * treatment stay identical across the page.
 */
export function SettingsSection({ id, className, "aria-label": ariaLabel, children }: SettingsSectionProps) {
  return (
    <section
      id={id}
      aria-label={ariaLabel}
      className={cn(
        "scroll-mt-24 space-y-5 rounded-xl border bg-card p-5 shadow-[var(--shadow-sm)] sm:p-6",
        className,
      )}
    >
      {children}
    </section>
  );
}

export type SettingsSectionHeaderProps = {
  icon: LucideIcon;
  title: ReactNode;
  description?: ReactNode;
  /** Right-aligned controls such as a switch or primary button. */
  actions?: ReactNode;
  className?: string;
};

export function SettingsSectionHeader({ icon: Icon, title, description, actions, className }: SettingsSectionHeaderProps) {
  return (
    <div className={cn("flex flex-wrap items-start justify-between gap-x-4 gap-y-3", className)}>
      <div className="flex min-w-0 items-start gap-3">
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-primary/12 text-primary ring-1 ring-primary/20">
          <Icon className="h-4 w-4" aria-hidden="true" />
        </div>
        <div className="min-w-0">
          <h3 className="text-base font-semibold leading-tight tracking-tight">{title}</h3>
          {description ? <p className="mt-1 text-sm leading-relaxed text-muted-foreground">{description}</p> : null}
        </div>
      </div>
      {actions ? <div className="flex shrink-0 items-center gap-2">{actions}</div> : null}
    </div>
  );
}

export type SettingsRowProps = {
  label: ReactNode;
  description?: ReactNode;
  /** Control rendered on the trailing edge (switch, segmented control, input). */
  children?: ReactNode;
  className?: string;
};

/**
 * One labelled control row. Stacks on narrow screens and aligns the control
 * to the trailing edge on wider ones.
 */
export function SettingsRow({ label, description, children, className }: SettingsRowProps) {
  return (
    <div
      className={cn(
        "flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between sm:gap-6",
        className,
      )}
    >
      <div className="min-w-0">
        <p className="text-sm font-medium leading-snug">{label}</p>
        {description ? <p className="mt-0.5 text-[13px] leading-relaxed text-muted-foreground">{description}</p> : null}
      </div>
      {children ? <div className="flex shrink-0 items-center">{children}</div> : null}
    </div>
  );
}

/** Bordered group that hosts one or more {@link SettingsRow}s. */
export function SettingsRowGroup({ className, children }: { className?: string; children: ReactNode }) {
  return <div className={cn("divide-y rounded-lg border bg-background/40", className)}>{children}</div>;
}
