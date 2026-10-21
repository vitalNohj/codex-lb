import { LayoutDashboard } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Switch } from "@/components/ui/switch";
import {
  DASHBOARD_LAYOUT_CARD_KEYS,
  DASHBOARD_LAYOUT_SECTION_KEYS,
  type DashboardLayoutVisibility,
} from "@/features/dashboard/layout";
import type { DashboardSettings, SettingsUpdateRequest } from "@/features/settings/schemas";
import { SettingsRow, SettingsRowGroup, SettingsSection, SettingsSectionHeader } from "@/features/settings/components/settings-section";

export type DashboardLayoutSettingsProps = {
  settings: DashboardSettings;
  busy: boolean;
  onSave: (patch: Partial<SettingsUpdateRequest>) => Promise<DashboardSettings | void>;
};

export function DashboardLayoutSettings({ settings, busy, onSave }: DashboardLayoutSettingsProps) {
  const { t } = useTranslation();
  const layout = settings.dashboardLayout;

  const saveFlag = (key: keyof DashboardLayoutVisibility, checked: boolean) => {
    // The server merges the flags present in this object. Sending the whole
    // snapshot would let a stale browser undo another browser's layout changes,
    // including when a conflict retry resends this same payload.
    void onSave({ dashboardLayout: { [key]: checked } });
  };

  return (
    <SettingsSection>
      <SettingsSectionHeader
        icon={LayoutDashboard}
        title={t("settings.dashboardLayout.title")}
        description={t("settings.dashboardLayout.description")}
      />
      <SettingsRowGroup>
        <p className="px-1 text-xs font-medium uppercase tracking-wider text-muted-foreground">
          {t("settings.dashboardLayout.groups.cards")}
        </p>
        {DASHBOARD_LAYOUT_CARD_KEYS.map((key) => (
          <LayoutSwitch
            key={key}
            label={t(`settings.dashboardLayout.cards.${key}.label`)}
            description={t(`settings.dashboardLayout.cards.${key}.description`)}
            ariaLabel={t(`settings.dashboardLayout.cards.${key}.ariaLabel`)}
            checked={layout[key]}
            disabled={busy}
            onCheckedChange={(checked) => saveFlag(key, checked)}
          />
        ))}
        <p className="px-1 pt-2 text-xs font-medium uppercase tracking-wider text-muted-foreground">
          {t("settings.dashboardLayout.groups.sections")}
        </p>
        {DASHBOARD_LAYOUT_SECTION_KEYS.map((key) => (
          <LayoutSwitch
            key={key}
            label={t(`settings.dashboardLayout.sections.${key}.label`)}
            description={t(`settings.dashboardLayout.sections.${key}.description`)}
            ariaLabel={t(`settings.dashboardLayout.sections.${key}.ariaLabel`)}
            checked={layout[key]}
            disabled={busy}
            onCheckedChange={(checked) => saveFlag(key, checked)}
          />
        ))}
      </SettingsRowGroup>
    </SettingsSection>
  );
}

type LayoutSwitchProps = {
  label: string;
  description: string;
  ariaLabel: string;
  checked: boolean;
  disabled: boolean;
  onCheckedChange: (checked: boolean) => void;
};

function LayoutSwitch({ label, description, ariaLabel, checked, disabled, onCheckedChange }: LayoutSwitchProps) {
  return (
    <SettingsRow label={label} description={description}>
      <Switch aria-label={ariaLabel} checked={checked} disabled={disabled} onCheckedChange={onCheckedChange} />
    </SettingsRow>
  );
}
