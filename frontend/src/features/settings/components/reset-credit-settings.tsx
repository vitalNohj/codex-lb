import { RotateCcw } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Switch } from "@/components/ui/switch";
import type { DashboardSettings, SettingsUpdateRequest } from "@/features/settings/schemas";
import { SettingsRow, SettingsRowGroup, SettingsSection, SettingsSectionHeader } from "@/features/settings/components/settings-section";

export type ResetCreditSettingsProps = {
  settings: DashboardSettings;
  busy: boolean;
  onSave: (patch: Partial<SettingsUpdateRequest>) => Promise<DashboardSettings | void>;
};

export function ResetCreditSettings({ settings, busy, onSave }: ResetCreditSettingsProps) {
  const { t } = useTranslation();
  const save = (patch: Partial<SettingsUpdateRequest>) => void onSave(patch);

  return (
    <SettingsSection>
      <SettingsSectionHeader
        icon={RotateCcw}
        title={t("settings.resetCredits.title")}
        description={t("settings.resetCredits.description")}
      />
      <SettingsRowGroup>
        <ResetCreditSwitchRow
          label={t("settings.resetCredits.badges.label")}
          description={t("settings.resetCredits.badges.description")}
          ariaLabel={t("settings.resetCredits.badges.ariaLabel")}
          checked={settings.showResetCreditBadges}
          disabled={busy}
          onCheckedChange={(checked) => save({ showResetCreditBadges: checked })}
        />
        <ResetCreditSwitchRow
          label={t("settings.resetCredits.expiryBadge.label")}
          description={t("settings.resetCredits.expiryBadge.description")}
          ariaLabel={t("settings.resetCredits.expiryBadge.ariaLabel")}
          checked={settings.showResetCreditExpiryBadge}
          disabled={busy}
          onCheckedChange={(checked) => save({ showResetCreditExpiryBadge: checked })}
        />
        <ResetCreditSwitchRow
          label={t("settings.resetCredits.autoRedeem.label")}
          description={t("settings.resetCredits.autoRedeem.description")}
          ariaLabel={t("settings.resetCredits.autoRedeem.ariaLabel")}
          checked={settings.autoRedeemResetCreditsBeforeExpiry}
          disabled={busy}
          onCheckedChange={(checked) => save({ autoRedeemResetCreditsBeforeExpiry: checked })}
        />
      </SettingsRowGroup>
    </SettingsSection>
  );
}

type ResetCreditSwitchRowProps = {
  label: string;
  description: string;
  ariaLabel: string;
  checked: boolean;
  disabled: boolean;
  onCheckedChange: (checked: boolean) => void;
};

function ResetCreditSwitchRow({
  label,
  description,
  ariaLabel,
  checked,
  disabled,
  onCheckedChange,
}: ResetCreditSwitchRowProps) {
  return (
    <SettingsRow label={label} description={description}>
      <Switch
        aria-label={ariaLabel}
        checked={checked}
        disabled={disabled}
        onCheckedChange={onCheckedChange}
      />
    </SettingsRow>
  );
}
