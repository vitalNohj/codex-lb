import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import { Shield } from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { z } from "zod";

import { AlertMessage } from "@/components/alert-message";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Form, FormControl, FormField, FormItem, FormLabel, FormMessage } from "@/components/ui/form";
import { InputOTP, InputOTPGroup, InputOTPSeparator, InputOTPSlot } from "@/components/ui/input-otp";
import { Switch } from "@/components/ui/switch";
import { disableTotp } from "@/features/auth/api";
import { TotpEnrollmentForm } from "@/features/auth/components/totp-enrollment-form";
import { useAuthStore } from "@/features/auth/hooks/use-auth";
import type { DashboardSettings, SettingsUpdateRequest } from "@/features/settings/schemas";
import { ApiError } from "@/lib/api-client";
import { getErrorMessage } from "@/utils/errors";
import { SettingsRow, SettingsRowGroup, SettingsSection, SettingsSectionHeader } from "@/features/settings/components/settings-section";

// NOTE: validation message is intentionally a translation key resolved at render time;
// keeping the schema decoupled from the i18n instance lets us continue to colocate it here.
const totpCodeSchema = z.object({
  code: z.string().length(6, "settings.totp.validation.codeLength"),
});

type TotpCodeValues = z.infer<typeof totpCodeSchema>;
type TotpDialog = "setup" | "disable" | null;

export type TotpSettingsProps = {
  settings: DashboardSettings;
  disabled?: boolean;
  /** The "require on login" toggle is a security setting; without it only the personal controls render. */
  canEditPolicy?: boolean;
  onSave: (patch: Partial<SettingsUpdateRequest>) => Promise<DashboardSettings | void>;
};

export function TotpSettings({ settings, disabled = false, canEditPolicy = true, onSave }: TotpSettingsProps) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const refreshSession = useAuthStore((state) => state.refreshSession);
  // Per account, so it comes from the session rather than the shared settings
  // cache (which would show the previous account's state right after a sign-in).
  const totpConfigured = useAuthStore((state) => state.totpConfigured);

  const [activeDialog, setActiveDialog] = useState<TotpDialog>(null);
  const [error, setError] = useState<string | null>(null);

  const disableForm = useForm<TotpCodeValues>({
    resolver: zodResolver(totpCodeSchema),
    defaultValues: { code: "" },
  });

  const lock = disabled || disableForm.formState.isSubmitting;

  const closeDialog = () => {
    setActiveDialog(null);
    setError(null);
    disableForm.reset();
  };

  const handleEnrolled = async () => {
    await refreshSession();
    void queryClient.invalidateQueries({ queryKey: ["settings", "detail"] });
    toast.success(t("settings.totp.toasts.configured"));
    closeDialog();
  };

  const handleDisable = async (values: TotpCodeValues) => {
    setError(null);
    try {
      await disableTotp({ code: values.code });
      await refreshSession();
      void queryClient.invalidateQueries({ queryKey: ["settings", "detail"] });
      toast.success(t("settings.totp.toasts.disabled"));
      closeDialog();
    } catch (caught) {
      // The break-glass guard can refuse here: this account may be the only
      // emergency way in while local sign-in is restricted (PLAN §4.2).
      setError(
        caught instanceof ApiError && caught.code === "last_break_glass_protected"
          ? t("access.errors.last_break_glass_protected")
          : getErrorMessage(caught),
      );
    }
  };

  return (
    <SettingsSection id="totp">
      <SettingsSectionHeader
        icon={Shield}
        title={t("settings.totp.title")}
        description={
          totpConfigured
            ? t("settings.totp.status.configured")
            : t("settings.totp.status.notConfigured")
        }
        actions={
          <>
            {totpConfigured ? (
              <Button
                type="button"
                size="sm"
                variant="outline"
                className="h-9 text-xs text-destructive hover:text-destructive"
                disabled={lock}
                onClick={() => setActiveDialog("disable")}
              >
                {t("settings.totp.actions.disable")}
              </Button>
            ) : (
              <Button
                type="button"
                size="sm"
                className="h-9 text-xs"
                disabled={lock}
                onClick={() => setActiveDialog("setup")}
              >
                {t("settings.totp.actions.enable")}
              </Button>
            )}
          </>
        }
      />

      {canEditPolicy ? (
        <SettingsRowGroup>
          <SettingsRow
            label={t("settings.totp.requireLogin.label")}
            description={t("settings.totp.requireLogin.description")}
          >
            <Switch
              checked={settings.totpRequiredOnLogin}
              disabled={lock}
              onCheckedChange={(checked) =>
                void onSave({ totpRequiredOnLogin: checked })
              }
            />
          </SettingsRow>
        </SettingsRowGroup>
      ) : null}

      {/* Setup dialog */}
      <Dialog open={activeDialog === "setup"} onOpenChange={(open) => !open && closeDialog()}>
        <DialogContent className="sm:max-w-sm">
          <DialogHeader>
            <DialogTitle>{t("settings.totp.setupDialog.title")}</DialogTitle>
            <DialogDescription>
              {t("settings.totp.setupDialog.description")}
            </DialogDescription>
          </DialogHeader>
          {activeDialog === "setup" ? (
            <TotpEnrollmentForm onEnrolled={handleEnrolled} onCancel={closeDialog} disabled={disabled} />
          ) : null}
        </DialogContent>
      </Dialog>

      {/* Disable dialog */}
      <Dialog open={activeDialog === "disable"} onOpenChange={(open) => !open && closeDialog()}>
        <DialogContent className="sm:max-w-sm">
          <DialogHeader>
            <DialogTitle>{t("settings.totp.disableDialog.title")}</DialogTitle>
            <DialogDescription>{t("settings.totp.disableDialog.description")}</DialogDescription>
          </DialogHeader>
          {error ? <AlertMessage variant="error">{error}</AlertMessage> : null}
          <Form {...disableForm}>
            <form onSubmit={disableForm.handleSubmit(handleDisable)} className="space-y-4">
              <FormField
                control={disableForm.control}
                name="code"
                render={({ field, fieldState }) => (
                  <FormItem className="flex flex-col items-center gap-2">
                    <FormLabel className="sr-only">{t("settings.totp.disableDialog.codeLabel")}</FormLabel>
                    <FormControl>
                      <InputOTP
                        maxLength={6}
                        value={field.value}
                        onChange={field.onChange}
                      >
                        <InputOTPGroup>
                          <InputOTPSlot index={0} />
                          <InputOTPSlot index={1} />
                          <InputOTPSlot index={2} />
                        </InputOTPGroup>
                        <InputOTPSeparator />
                        <InputOTPGroup>
                          <InputOTPSlot index={3} />
                          <InputOTPSlot index={4} />
                          <InputOTPSlot index={5} />
                        </InputOTPGroup>
                      </InputOTP>
                    </FormControl>
                    {fieldState.error?.message ? (
                      <FormMessage>{t(fieldState.error.message)}</FormMessage>
                    ) : (
                      <FormMessage />
                    )}
                  </FormItem>
                )}
              />
              <DialogFooter>
                <Button type="button" variant="outline" onClick={closeDialog} disabled={lock}>
                  {t("common.cancel")}
                </Button>
                <Button type="submit" variant="destructive" disabled={lock}>
                  {t("settings.totp.disableDialog.submit")}
                </Button>
              </DialogFooter>
            </form>
          </Form>
        </DialogContent>
      </Dialog>
    </SettingsSection>
  );
}
