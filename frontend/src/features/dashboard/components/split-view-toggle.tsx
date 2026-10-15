import { Columns2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import { cn } from "@/lib/utils";

type SplitViewToggleProps = {
  pressed: boolean;
  onPressedChange: (pressed: boolean) => void;
};

/** Header toggle that switches the dashboard into its wide-screen column layout. */
export function SplitViewToggle({ pressed, onPressedChange }: SplitViewToggleProps) {
  const { t } = useTranslation();
  const label = t("dashboard.page.splitView");

  return (
    <button
      type="button"
      aria-pressed={pressed}
      title={label}
      onClick={() => onPressedChange(!pressed)}
      className={cn(
        "inline-flex h-8 items-center gap-1.5 rounded-md border px-2.5 text-xs font-medium transition-colors",
        pressed
          ? "border-primary/40 bg-primary/10 text-primary"
          : "bg-background text-muted-foreground hover:bg-accent hover:text-accent-foreground",
      )}
    >
      <Columns2 className="h-3.5 w-3.5" aria-hidden="true" />
      {label}
    </button>
  );
}
