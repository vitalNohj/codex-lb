import { useTranslation } from "react-i18next";

import { Switch } from "@/components/ui/switch";
import { SettingsRow } from "@/features/settings/components/settings-section";

export type ApiKeyQuotaPrivacyToggleProps = {
  enabled: boolean;
  disabled?: boolean;
  onChange: (enabled: boolean) => void;
};

export function ApiKeyQuotaPrivacyToggle({
  enabled,
  disabled = false,
  onChange,
}: ApiKeyQuotaPrivacyToggleProps) {
  const { t } = useTranslation();
  return (
    <SettingsRow label={t("apiKeys.quotaPrivacy.title")} description={t("apiKeys.quotaPrivacy.description")}>
      <Switch checked={enabled} disabled={disabled} onCheckedChange={onChange} />
    </SettingsRow>
  );
}
