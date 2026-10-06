import type { DashboardSettings } from "@/features/settings/schemas";
import { OMNIROUTE_ENABLED } from "@/lib/product-capabilities";

/**
 * One routable (integration, model) pair for alias-pool targets.
 *
 * ``target`` is the explicit form the backend resolves
 * (``<providerKey>::<model>``): a pool that chains one model across several
 * integrations names each card, because a bare model id would always resolve
 * to the starred card.
 */
export type IntegrationModelTarget = {
  /** Backend provider key, matching the star map's values. */
  providerKey: string;
  integrationName: string;
  model: string;
  target: string;
};

type Card = {
  providerKey: string;
  name: string;
  models: string[];
};

function cardsFrom(settings: DashboardSettings): Card[] {
  const cards: Card[] = [
    { providerKey: "claude", name: "CLIProxyAPI", models: settings.claudeSidecarFullModels ?? [] },
    { providerKey: "openrouter", name: "OpenRouter", models: settings.openrouterSidecarFullModels ?? [] },
    { providerKey: "orcarouter", name: "OrcaRouter", models: settings.orcarouterSidecarFullModels ?? [] },
    { providerKey: "ollama", name: "Ollama", models: settings.ollamaSidecarFullModels ?? [] },
    { providerKey: "opencode_go", name: "OpenCode Go", models: settings.opencodeGoSidecarFullModels ?? [] },
  ];
  if (OMNIROUTE_ENABLED) {
    cards.push({
      providerKey: "omniroute",
      name: "OmniRoute",
      models: settings.omnirouteSidecarFullModels ?? settings.omnirouteSidecarSelectedModels ?? [],
    });
  }
  for (const endpoint of settings.openaiCompatEndpoints ?? []) {
    cards.push({
      providerKey: `openai_compat:${endpoint.id}`,
      name: endpoint.name,
      models: endpoint.fullModels ?? [],
    });
  }
  return cards;
}

/** Every (integration, full model) pair across the configured cards. */
export function listIntegrationModelTargets(settings: DashboardSettings): IntegrationModelTarget[] {
  const targets: IntegrationModelTarget[] = [];
  const seen = new Set<string>();
  for (const card of cardsFrom(settings)) {
    for (const model of card.models) {
      const trimmed = model.trim();
      if (!trimmed) {
        continue;
      }
      const key = `${card.providerKey}::${trimmed.toLowerCase()}`;
      if (seen.has(key)) {
        continue;
      }
      seen.add(key);
      targets.push({
        providerKey: card.providerKey,
        integrationName: card.name,
        model: trimmed,
        target: `${card.providerKey}::${trimmed}`,
      });
    }
  }
  return targets;
}