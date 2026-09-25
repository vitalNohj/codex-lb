import { Upload } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Switch } from "@/components/ui/switch";
import type { DashboardSettings, SettingsUpdateRequest } from "@/features/settings/schemas";
import { SettingsRow, SettingsRowGroup, SettingsSection, SettingsSectionHeader } from "@/features/settings/components/settings-section";

export type ImportSettingsProps = {
  settings: DashboardSettings;
  busy: boolean;
  onSave: (patch: Partial<SettingsUpdateRequest>) => Promise<DashboardSettings | void>;
};

export function ImportSettings({ settings, busy, onSave }: ImportSettingsProps) {
  const { t } = useTranslation();
  const save = (patch: Partial<SettingsUpdateRequest>) => void onSave(patch);

  return (
    <SettingsSection>
      <SettingsSectionHeader
        icon={Upload}
        title={t("settings.import.title")}
        description={t("settings.import.description")}
      />
      <SettingsRowGroup>
        <SettingsRow
          label={t("settings.import.allowDuplicates.label")}
          description={t("settings.import.allowDuplicates.description")}
        >
          <Switch
            aria-label={t("settings.import.allowDuplicates.ariaLabel")}
            checked={settings.importWithoutOverwrite}
            disabled={busy}
            onCheckedChange={(checked) => save({ importWithoutOverwrite: checked })}
          />
        </SettingsRow>
      </SettingsRowGroup>
    </SettingsSection>
  );
}
