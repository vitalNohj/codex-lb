import { useTranslation } from "react-i18next";

import { Switch } from "@/components/ui/switch";
import { SettingsRow } from "@/features/settings/components/settings-section";

export type ApiKeyAuthToggleProps = {
  enabled: boolean;
  disabled?: boolean;
  onChange: (enabled: boolean) => void;
};

export function ApiKeyAuthToggle({ enabled, disabled = false, onChange }: ApiKeyAuthToggleProps) {
  const { t } = useTranslation();
  return (
    <SettingsRow label={t("apiKeys.authToggle.title")} description={t("apiKeys.authToggle.description")}>
      <Switch checked={enabled} disabled={disabled} onCheckedChange={onChange} />
    </SettingsRow>
  );
}
