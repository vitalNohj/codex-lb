import { Monitor, Moon, Palette, Sun } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Switch } from "@/components/ui/switch";
import { useAccountQuotaDisplayStore, type AccountQuotaDisplayPreference } from "@/hooks/use-account-quota-display";
import { useDashboardPreferencesStore } from "@/hooks/use-dashboard-preferences";
import { useThemeStore, type ThemePreference } from "@/hooks/use-theme";
import { useTimeFormatStore, type TimeFormatPreference } from "@/hooks/use-time-format";
import { useDateDisplayFormatStore, type DateDisplayFormat } from "@/hooks/use-date-format";
import { cn } from "@/lib/utils";
import { SettingsRow, SettingsRowGroup, SettingsSection, SettingsSectionHeader } from "@/features/settings/components/settings-section";

const SEGMENT_GROUP = "flex items-center gap-1 rounded-lg border bg-muted/60 p-1";
const SEGMENT_BUTTON = "rounded-md px-3 py-1.5 text-left text-sm font-medium transition-colors duration-200";
const SEGMENT_ACTIVE = "bg-background text-foreground shadow-[var(--shadow-sm)] ring-1 ring-border";
const SEGMENT_IDLE = "text-muted-foreground hover:text-foreground";

const THEME_OPTIONS: { value: ThemePreference; labelKey: string; icon: typeof Sun }[] = [
  { value: "light", labelKey: "settings.appearance.theme.light", icon: Sun },
  { value: "dark", labelKey: "settings.appearance.theme.dark", icon: Moon },
  { value: "auto", labelKey: "settings.appearance.theme.auto", icon: Monitor },
];

const TIME_FORMAT_OPTIONS: { value: TimeFormatPreference; labelKey: string }[] = [
  { value: "12h", labelKey: "settings.appearance.timeFormat.h12" },
  { value: "24h", labelKey: "settings.appearance.timeFormat.h24" },
];

const DATE_FORMAT_OPTIONS: { value: DateDisplayFormat; labelKey: string }[] = [
  { value: "default", labelKey: "settings.appearance.dateFormat.default" },
  { value: "iso8601", labelKey: "settings.appearance.dateFormat.iso8601" },
];

const QUOTA_DISPLAY_OPTIONS: {
  value: AccountQuotaDisplayPreference;
  labelKey: string;
  descriptionKey: string;
}[] = [
  {
    value: "5h",
    labelKey: "settings.appearance.accountRows.fiveHour",
    descriptionKey: "settings.appearance.accountRows.fiveHourDescription",
  },
  {
    value: "weekly",
    labelKey: "settings.appearance.accountRows.weekly",
    descriptionKey: "settings.appearance.accountRows.weeklyDescription",
  },
  {
    value: "both",
    labelKey: "settings.appearance.accountRows.both",
    descriptionKey: "settings.appearance.accountRows.bothDescription",
  },
];

export function AppearanceSettings() {
  const { t } = useTranslation();
  const preference = useThemeStore((s) => s.preference);
  const setTheme = useThemeStore((s) => s.setTheme);
  const timeFormat = useTimeFormatStore((s) => s.timeFormat);
  const setTimeFormat = useTimeFormatStore((s) => s.setTimeFormat);
  const quotaDisplay = useAccountQuotaDisplayStore((s) => s.quotaDisplay);
  const setQuotaDisplay = useAccountQuotaDisplayStore((s) => s.setQuotaDisplay);
  const accountBurnrateEnabled = useDashboardPreferencesStore((s) => s.accountBurnrateEnabled);
  const setAccountBurnrateEnabled = useDashboardPreferencesStore((s) => s.setAccountBurnrateEnabled);
  const dateDisplayFormat = useDateDisplayFormatStore((s) => s.dateDisplayFormat);
  const setDateDisplayFormat = useDateDisplayFormatStore((s) => s.setDateDisplayFormat);

  return (
    <SettingsSection>
      <SettingsSectionHeader
        icon={Palette}
        title={t("settings.appearance.title")}
        description={t("settings.appearance.description")}
      />

      <SettingsRowGroup>
          <SettingsRow
            label={t("settings.appearance.theme.label")}
            description={t("settings.appearance.theme.description")}
          >
            <div className={SEGMENT_GROUP}>
              {THEME_OPTIONS.map(({ value, labelKey, icon: Icon }) => (
                <button
                  key={value}
                  type="button"
                  aria-pressed={preference === value}
                  onClick={() => setTheme(value)}
                  className={cn(SEGMENT_BUTTON, "flex items-center gap-1.5", preference === value ? SEGMENT_ACTIVE : SEGMENT_IDLE)}
                >
                  <Icon className="h-3.5 w-3.5" />
                  {t(labelKey)}
                </button>
              ))}
            </div>
          </SettingsRow>

          <SettingsRow
            label={t("settings.appearance.timeFormat.label")}
            description={t("settings.appearance.timeFormat.description")}
          >
            <div className={SEGMENT_GROUP}>
              {TIME_FORMAT_OPTIONS.map(({ value, labelKey }) => (
                <button
                  key={value}
                  type="button"
                  aria-pressed={timeFormat === value}
                  onClick={() => setTimeFormat(value)}
                  className={cn(SEGMENT_BUTTON, timeFormat === value ? SEGMENT_ACTIVE : SEGMENT_IDLE)}
                >
                  <span className="block">{t(labelKey)}</span>
                </button>
              ))}
            </div>
          </SettingsRow>

          <SettingsRow
            label={t("settings.appearance.dateFormat.label")}
            description={t("settings.appearance.dateFormat.description")}
          >
            <div className={SEGMENT_GROUP}>
              {DATE_FORMAT_OPTIONS.map(({ value, labelKey }) => (
                <button
                  key={value}
                  type="button"
                  aria-pressed={dateDisplayFormat === value}
                  onClick={() => setDateDisplayFormat(value)}
                  className={cn(SEGMENT_BUTTON, dateDisplayFormat === value ? SEGMENT_ACTIVE : SEGMENT_IDLE)}
                >
                  <span className="block">{t(labelKey)}</span>
                </button>
              ))}
            </div>
          </SettingsRow>

          <SettingsRow
            label={t("settings.appearance.accountRows.label")}
            description={t("settings.appearance.accountRows.description")}
          >
            <div className={SEGMENT_GROUP}>
              {QUOTA_DISPLAY_OPTIONS.map(({ value, labelKey, descriptionKey }) => (
                <button
                  key={value}
                  type="button"
                  aria-pressed={quotaDisplay === value}
                  title={t(descriptionKey)}
                  onClick={() => setQuotaDisplay(value)}
                  className={cn(SEGMENT_BUTTON, quotaDisplay === value ? SEGMENT_ACTIVE : SEGMENT_IDLE)}
                >
                  <span className="block">{t(labelKey)}</span>
                </button>
              ))}
            </div>
          </SettingsRow>

          <SettingsRow
            label={t("settings.appearance.burnProjection.label")}
            description={t("settings.appearance.burnProjection.description")}
          >
            <Switch
              aria-label={t("settings.appearance.burnProjection.ariaLabel")}
              checked={accountBurnrateEnabled}
              onCheckedChange={setAccountBurnrateEnabled}
            />
          </SettingsRow>
      </SettingsRowGroup>
    </SettingsSection>
  );
}
