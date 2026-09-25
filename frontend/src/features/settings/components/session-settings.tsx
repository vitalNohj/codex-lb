import { useState } from "react";
import { TimerReset } from "lucide-react";
import { Trans, useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { DashboardSettings, SettingsUpdateRequest } from "@/features/settings/schemas";
import { SettingsRow, SettingsRowGroup, SettingsSection, SettingsSectionHeader } from "@/features/settings/components/settings-section";

export type SessionSettingsProps = {
  settings: DashboardSettings;
  busy: boolean;
  onSave: (patch: Partial<SettingsUpdateRequest>) => Promise<DashboardSettings | void>;
};

const MIN_TTL_SECONDS = 3600;
const WARNING_THRESHOLD_SECONDS = 30 * 24 * 60 * 60;
const INTEGER_HOURS_PATTERN = /^\d+$/;

function formatStoredHours(ttlSeconds: number): string {
  const hours = ttlSeconds / 3600;
  // Preserve sub-hour TTLs without silently rounding them when the backend
  // already accepts any value >= MIN_TTL_SECONDS.
  return Number.isInteger(hours) ? String(hours) : hours.toFixed(2);
}

export function SessionSettings({ settings, busy, onSave }: SessionSettingsProps) {
  const { t } = useTranslation();
  const [sessionHours, setSessionHours] = useState(formatStoredHours(settings.dashboardSessionTtlSeconds));

  const trimmed = sessionHours.trim();
  const isInteger = INTEGER_HOURS_PATTERN.test(trimmed);
  const parsedHours = isInteger ? Number.parseInt(trimmed, 10) : Number.NaN;
  const parsedSeconds = parsedHours * 3600;
  const valid = isInteger && Number.isFinite(parsedHours) && parsedHours > 0 && parsedSeconds >= MIN_TTL_SECONDS;
  const changed = valid && parsedSeconds !== settings.dashboardSessionTtlSeconds;
  const showLongSessionWarning = valid && parsedSeconds > WARNING_THRESHOLD_SECONDS;
  const showInvalidInputWarning = trimmed !== "" && !valid;

  const save = () =>
    void onSave({ dashboardSessionTtlSeconds: parsedSeconds });

  return (
    <SettingsSection>
      <SettingsSectionHeader
        icon={TimerReset}
        title={t("settings.session.title")}
        description={t("settings.session.description")}
      />

      <SettingsRowGroup>
        <SettingsRow
          label={t("settings.session.lifetime.label")}
          description={t("settings.session.lifetime.description")}
        >
          <div className="flex items-center gap-2">
            <Input
              type="number"
              min={1}
              step={1}
              inputMode="numeric"
              value={sessionHours}
              disabled={busy}
              onChange={(event) => setSessionHours(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && changed) {
                  save();
                }
              }}
              className="h-9 w-24 text-sm tabular-nums"
              aria-label={t("settings.session.lifetime.ariaLabel")}
            />
            <span className="text-sm text-muted-foreground">{t("settings.session.lifetime.hoursSuffix")}</span>
            <Button
              type="button"
              size="sm"
              variant="outline"
              className="h-9 text-xs"
              disabled={busy || !changed}
              onClick={save}
            >
              {t("settings.session.lifetime.save")}
            </Button>
          </div>
        </SettingsRow>
      </SettingsRowGroup>

      {showInvalidInputWarning ? (
        <div className="rounded-lg border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm font-medium text-destructive">
          <Trans i18nKey="settings.session.lifetime.invalid" components={[<code key="0" />]} />
        </div>
      ) : null}
      {showLongSessionWarning ? (
        <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm font-medium text-amber-900 dark:text-amber-200">
          {t("settings.session.lifetime.longWarning")}
        </div>
      ) : null}
    </SettingsSection>
  );
}
