import { KeyRound } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { useAuthStore } from "@/features/auth/hooks/use-auth";
import { PasswordChangeDialog } from "@/features/settings/components/password-change-dialog";
import { PasswordRemoveDialog } from "@/features/settings/components/password-remove-dialog";
import { PasswordSetupDialog } from "@/features/settings/components/password-setup-dialog";
import { PasswordVerifyDialog } from "@/features/settings/components/password-verify-dialog";
import { SettingsSection, SettingsSectionHeader } from "@/features/settings/components/settings-section";

type PasswordDialog = "setup" | "change" | "remove" | "verify" | null;

export type PasswordSettingsProps = {
  disabled?: boolean;
};

export function PasswordSettings({ disabled = false }: PasswordSettingsProps) {
  const { t } = useTranslation();
  // Whether a password exists to change or remove; accounts that sign in through
  // the reverse proxy alone must not turn this card into "Login to manage".
  const passwordRequired = useAuthStore((s) => s.localPasswordConfigured);
  const authMode = useAuthStore((s) => s.authMode);
  const passwordManagementEnabled = useAuthStore((s) => s.passwordManagementEnabled);
  const passwordSessionActive = useAuthStore((s) => s.passwordSessionActive);
  const authenticated = useAuthStore((s) => s.authenticated);

  const [activeDialog, setActiveDialog] = useState<PasswordDialog>(null);

  const lock = disabled || !passwordManagementEnabled;
  const closeIfMatches = (dialog: PasswordDialog) => (open: boolean) => {
    if (!open && activeDialog === dialog) {
      setActiveDialog(null);
    }
  };

  const handleSetupOpenChange = (open: boolean) => {
    if (open) {
      setActiveDialog("setup");
    } else if (activeDialog === "setup") {
      setActiveDialog(null);
    }
  };

  const statusMessage = !passwordManagementEnabled
    ? t("settings.password.status.disabled")
    : authMode === "trusted_header"
      ? passwordRequired
        ? t("settings.password.status.fallbackConfigured")
        : t("settings.password.status.fallbackMissing")
      : passwordRequired
        ? t("settings.password.status.configured")
        : t("settings.password.status.notSet");

  return (
    <SettingsSection>
      <SettingsSectionHeader
        icon={KeyRound}
        title={t("settings.password.title")}
        description={statusMessage}
        actions={
          <>
            {!passwordManagementEnabled ? null : passwordRequired && passwordSessionActive ? (
              <>
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  className="h-9 text-xs"
                  disabled={lock}
                  onClick={() => setActiveDialog("change")}
                >
                  {t("settings.password.actions.change")}
                </Button>
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  className="h-9 text-xs text-destructive hover:text-destructive"
                  disabled={lock}
                  onClick={() => setActiveDialog("remove")}
                >
                  {t("settings.password.actions.remove")}
                </Button>
              </>
            ) : passwordRequired && authenticated && !passwordSessionActive ? (
              <Button
                type="button"
                size="sm"
                variant="outline"
                className="h-9 text-xs"
                disabled={disabled}
                onClick={() => setActiveDialog("verify")}
              >
                {t("settings.password.actions.loginToManage")}
              </Button>
            ) : !passwordRequired ? (
              <PasswordSetupDialog
                open={activeDialog === "setup"}
                onOpenChange={handleSetupOpenChange}
                disabled={disabled}
              >
                <Button type="button" size="sm" className="h-9 text-xs" disabled={lock}>
                  {t("settings.password.actions.set")}
                </Button>
              </PasswordSetupDialog>
            ) : null}
          </>
        }
      />

      <PasswordChangeDialog
        open={activeDialog === "change"}
        onOpenChange={closeIfMatches("change")}
        disabled={disabled}
      />
      <PasswordRemoveDialog
        open={activeDialog === "remove"}
        onOpenChange={closeIfMatches("remove")}
        disabled={disabled}
      />
      <PasswordVerifyDialog
        open={activeDialog === "verify"}
        onOpenChange={closeIfMatches("verify")}
        disabled={disabled}
      />
    </SettingsSection>
  );
}
