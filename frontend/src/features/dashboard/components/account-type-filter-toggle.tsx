import { cn } from "@/lib/utils";
import {
  ACCOUNT_TYPE_KEYS,
  type AccountTypeKey,
  type AccountTypeVisibility,
} from "@/hooks/use-dashboard-preferences";

type AccountTypeFilterToggleProps = {
  value: AccountTypeVisibility;
  onToggle: (key: AccountTypeKey) => void;
};

const LABELS: Record<AccountTypeKey, string> = {
  codex: "Codex",
  cliproxy: "CLIProxy",
  openrouter: "OpenRouter",
  omniroute: "Omniroute",
};

export function AccountTypeFilterToggle({ value, onToggle }: AccountTypeFilterToggleProps) {
  return (
    <div
      className="inline-flex h-8 items-center gap-0.5 rounded-md border bg-background p-0.5"
      role="group"
      aria-label="Account type visibility"
    >
      {ACCOUNT_TYPE_KEYS.map((key) => {
        const enabled = value[key];
        const label = LABELS[key];
        return (
          <button
            key={key}
            type="button"
            aria-pressed={enabled}
            aria-label={`${enabled ? "Hide" : "Show"} ${label} accounts`}
            title={`${enabled ? "Hide" : "Show"} ${label} accounts`}
            onClick={() => onToggle(key)}
            className={cn(
              "inline-flex h-6 items-center rounded-[5px] px-2 text-xs font-medium transition-colors",
              enabled
                ? "bg-accent text-accent-foreground shadow-sm"
                : "text-muted-foreground hover:bg-accent/60 hover:text-accent-foreground",
            )}
          >
            {label}
          </button>
        );
      })}
    </div>
  );
}
