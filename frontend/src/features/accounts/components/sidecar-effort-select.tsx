import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { buildSettingsUpdateRequest } from "@/features/settings/payload";
import {
  REASONING_EFFORT_OPTIONS,
  REASONING_EFFORT_UNSET,
} from "@/features/settings/reasoning-effort";
import type {
  DashboardSettings,
  SettingsUpdateRequest,
  SidecarReasoningEffort,
} from "@/features/settings/schemas";
import { useSettings } from "@/features/settings/hooks/use-settings";

type EffortFieldKey =
  | "claudeSidecarDefaultReasoningEffort"
  | "openrouterSidecarDefaultReasoningEffort"
  | "omnirouteSidecarDefaultReasoningEffort"
  | "ollamaSidecarDefaultReasoningEffort";

function fieldForProvider(provider: string | null | undefined): EffortFieldKey {
  if (provider === "openrouter") {
    return "openrouterSidecarDefaultReasoningEffort";
  }
  if (provider === "omniroute") {
    return "omnirouteSidecarDefaultReasoningEffort";
  }
  if (provider === "ollama") {
    return "ollamaSidecarDefaultReasoningEffort";
  }
  return "claudeSidecarDefaultReasoningEffort";
}

export function SidecarEffortSelect({
  provider,
}: {
  provider: string | null | undefined;
}) {
  const { settingsQuery, updateSettingsMutation } = useSettings();
  const settings = settingsQuery.data;
  if (!settings) {
    return null;
  }
  const field = fieldForProvider(provider);
  const current = (settings as DashboardSettings)[field] ?? null;
  const busy = updateSettingsMutation.isPending;
  const handleChange = (value: string) => {
    const effort: SidecarReasoningEffort | null =
      value === REASONING_EFFORT_UNSET ? null : (value as SidecarReasoningEffort);
    const patch = { [field]: effort } as Partial<SettingsUpdateRequest>;
    void updateSettingsMutation.mutateAsync(
      buildSettingsUpdateRequest(settings, patch),
    );
  };
  return (
    <div className="flex items-center justify-between gap-2 rounded-lg border bg-muted/20 px-2.5 py-2 text-xs">
      <label htmlFor="sidecar-effort-select" className="font-medium">
        Default reasoning effort
      </label>
      <Select value={current ?? REASONING_EFFORT_UNSET} onValueChange={handleChange}>
        <SelectTrigger id="sidecar-effort-select" className="h-7 w-40 text-xs" disabled={busy}>
          <SelectValue />
        </SelectTrigger>
        <SelectContent align="end">
          <SelectItem value={REASONING_EFFORT_UNSET}>Use client / model default</SelectItem>
          {REASONING_EFFORT_OPTIONS.map((option) => (
            <SelectItem key={option.value} value={option.value}>
              {option.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}
