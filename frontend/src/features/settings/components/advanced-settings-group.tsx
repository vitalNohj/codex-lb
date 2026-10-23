import { ChevronRight, SlidersHorizontal } from "lucide-react";
import { useIsFetching, useQueryClient, type Query, type QueryKey } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { cn } from "@/lib/utils";

const EMPTY_QUERY_KEYS: readonly QueryKey[] = [];

/** i18n keys of the trigger's heading, sub-line and open/close labels. */
export type SettingsGroupLabelKeys = {
  title: string;
  description: string;
  show: string;
  hide: string;
};

const ADVANCED_LABELS: SettingsGroupLabelKeys = {
  title: "settings.advanced.title",
  description: "settings.advanced.description",
  show: "settings.advanced.show",
  hide: "settings.advanced.hide",
};

export type AdvancedSettingsGroupProps = {
  children: ReactNode;
  defaultOpen?: boolean;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  scrollToId?: string;
  waitForQueryKeys?: readonly QueryKey[];
  /** Defaults to the Advanced group's own copy; a second group passes its own. */
  labels?: SettingsGroupLabelKeys;
  /** Interpolation values for `labels.description` (a status summary counts things). */
  descriptionValues?: Record<string, string | number>;
  /** Applied to the sub-line, so a group can assert what its collapsed copy says. */
  descriptionTestId?: string;
};

/**
 * Collapsed-by-default container for power-user settings sections.
 *
 * Children are unmounted while the group is closed, so section data queries
 * only fire once the operator expands the group. Reused by the Organisation
 * group, which passes its own `labels`; the copy is the only difference.
 */
export function AdvancedSettingsGroup({
  children,
  defaultOpen = false,
  open: controlledOpen,
  onOpenChange,
  scrollToId,
  waitForQueryKeys = EMPTY_QUERY_KEYS,
  labels = ADVANCED_LABELS,
  descriptionValues,
  descriptionTestId,
}: AdvancedSettingsGroupProps) {
  const { t } = useTranslation();
  const [localOpen, setLocalOpen] = useState(defaultOpen);
  const open = controlledOpen ?? localOpen;
  const setOpen = onOpenChange ?? setLocalOpen;
  const queryClient = useQueryClient();
  const isLayoutQuery = useCallback(
    (query: Query) =>
      waitForQueryKeys.some((prefix) =>
        prefix.every((value, index) => Object.is(query.queryKey[index], value)),
      ),
    [waitForQueryKeys],
  );
  const fetchingQueries = useIsFetching({ predicate: isLayoutQuery });
  const scrolledToIdRef = useRef<string | undefined>(undefined);

  useEffect(() => {
    if (!open || !scrollToId) {
      scrolledToIdRef.current = undefined;
      return;
    }
    if (scrolledToIdRef.current === scrollToId) {
      return;
    }
    const frame = window.requestAnimationFrame(() => {
      if (queryClient.isFetching({ predicate: isLayoutQuery }) > 0) {
        return;
      }
      const target = document.getElementById(scrollToId);
      if (!target) {
        return;
      }
      target.scrollIntoView({ block: "start" });
      scrolledToIdRef.current = scrollToId;
    });
    return () => {
      window.cancelAnimationFrame(frame);
    };
  }, [fetchingQueries, isLayoutQuery, open, queryClient, scrollToId]);

  return (
    <Collapsible
      open={open}
      onOpenChange={setOpen}
      className="rounded-xl border border-dashed bg-card/60 shadow-[var(--shadow-sm)] data-[state=open]:border-solid data-[state=open]:bg-card"
    >
      <CollapsibleTrigger
        aria-label={open ? t(labels.hide) : t(labels.show)}
        className="flex w-full items-center gap-3 rounded-xl p-5 text-left transition-colors hover:bg-accent/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60 sm:p-6"
      >
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-primary/12 text-primary ring-1 ring-primary/20">
          <SlidersHorizontal className="h-4 w-4" aria-hidden="true" />
        </span>
        <span className="min-w-0 flex-1">
          <span className="block text-base font-semibold leading-tight tracking-tight">{t(labels.title)}</span>
          <span data-testid={descriptionTestId} className="mt-1 block text-sm leading-relaxed text-muted-foreground">
            {t(labels.description, descriptionValues)}
          </span>
        </span>
        <ChevronRight
          aria-hidden="true"
          className={cn("h-5 w-5 shrink-0 text-muted-foreground transition-transform duration-200", open && "rotate-90")}
        />
      </CollapsibleTrigger>
      <CollapsibleContent className="space-y-5 border-t p-4 sm:p-6">
        {children}
      </CollapsibleContent>
    </Collapsible>
  );
}
