import { z } from "zod";

/**
 * How an account's exclusion list must be presented.
 *
 * Mirrors `ExcludedModelsState` in app/modules/claude_sidecar/excluded_models.py.
 *
 * - `available`: read verbatim from CLIProxyAPI, safe to edit and save back.
 * - `unreadable`: the read failed, so editing is locked and the failure shown.
 * - `unsupported`: the row has no CLIProxyAPI auth file to edit at all.
 */
export const ExcludedModelsStateSchema = z.enum(["available", "unreadable", "unsupported"]);

export type ExcludedModelsState = z.infer<typeof ExcludedModelsStateSchema>;
