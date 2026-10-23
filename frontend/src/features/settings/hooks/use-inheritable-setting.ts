import { useCallback } from "react";

import type { DashboardSettings, SettingProvenance, SettingsUpdateRequest } from "@/features/settings/schemas";

// Update-request fields that accept an explicit null to return to inheritance.
export type InheritableSettingField = {
  [K in keyof SettingsUpdateRequest]-?: null extends SettingsUpdateRequest[K] ? K : never;
}[keyof SettingsUpdateRequest];

/**
 * Provenance of one inheritable setting (keyed by its backend name) plus a
 * reset action that PUTs an explicit null so the setting returns to inheriting
 * the environment value or code default.
 */
export function useInheritableSetting(
  settings: DashboardSettings,
  name: string,
  field: InheritableSettingField,
  onSave: (patch: Partial<SettingsUpdateRequest>) => Promise<DashboardSettings | void>,
): { provenance: SettingProvenance | undefined; resetToInherited: () => Promise<void> } {
  const provenance = settings.provenance?.[name];
  // Fork: saves send only the patch; the settings mutation stamps the cached
  // version and retries a scalar conflict once (see persistSettingsPatch).
  const resetToInherited = useCallback(
    () => onSave({ [field]: null }).then(() => undefined),
    [field, onSave],
  );
  return { provenance, resetToInherited };
}
