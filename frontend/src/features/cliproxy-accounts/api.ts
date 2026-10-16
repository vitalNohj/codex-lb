import { z } from "zod";

import { get, patch, post, put } from "@/lib/api-client";

const CliproxyConfigStatusSchema = z.enum([
  "healthy",
  "disabled",
  "not_configured",
  "unreachable",
  "unauthorized",
  "error",
]);

export const CliproxyConfigViewSchema = z.object({
  status: CliproxyConfigStatusSchema,
  message: z.string().nullable().optional(),
  yaml: z.string().nullable().optional(),
  contentSha256: z.string().nullable().optional(),
  sessionAffinity: z.boolean().nullable().optional(),
  forceModelPrefix: z.boolean().nullable().optional(),
  rollbackAvailable: z.boolean(),
});

export const CliproxyConfigPreviewSchema = z.object({
  status: CliproxyConfigStatusSchema,
  message: z.string().nullable().optional(),
  diff: z.string(),
  changed: z.boolean(),
  contentSha256: z.string().nullable().optional(),
});

export type CliproxyConfigView = z.infer<typeof CliproxyConfigViewSchema>;
export type CliproxyConfigPreview = z.infer<typeof CliproxyConfigPreviewSchema>;

export const CLIPROXY_CONFIG_QUERY_KEY = ["cliproxy", "config"] as const;

const CONFIG_PATH = "/api/cliproxy/config";

export function getCliproxyConfig() {
  return get(CONFIG_PATH, CliproxyConfigViewSchema);
}

export function previewCliproxyConfig(body: { yaml: string; contentSha256: string }) {
  return post(`${CONFIG_PATH}/preview`, CliproxyConfigPreviewSchema, { body });
}

export function replaceCliproxyConfig(body: { yaml: string; contentSha256: string; confirm: true }) {
  return put(CONFIG_PATH, CliproxyConfigViewSchema, { body });
}

export function rollbackCliproxyConfig(body: { contentSha256: string; confirm: true }) {
  return post(`${CONFIG_PATH}/rollback`, CliproxyConfigViewSchema, { body });
}

export function patchCliproxyRoutingFlag(field: "force-model-prefix" | "session-affinity", body: {
  enabled: boolean;
  contentSha256: string;
}) {
  return patch(`${CONFIG_PATH}/routing/${field}`, CliproxyConfigViewSchema, { body });
}
