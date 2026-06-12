# Refine OpenRouter Sidecar Settings UI Context

## Purpose and scope

UI-only refinement of the dashboard OpenRouter sidecar settings section. No backend behavior, API, or schema changes; the section reuses the existing `/api/settings` PATCH surface and `/api/openrouter-sidecar/{status,test,models}` endpoints shipped in `add-openrouter-sidecar-routing`.

## Decisions

- The settings section prioritizes the two fields operators actually need: the OpenRouter API key and the model routing prefixes. Base URL and timeouts (connect, request, models cache TTL) remain editable but live in a collapsed Advanced block with unchanged defaults.
- The section layout matches the Claude sidecar section (icon header, status badge, help callout, divided enable row) so the two sidecars read consistently.
- A curated popular-models list (`POPULAR_OPENROUTER_MODELS`) is hardcoded in the frontend. When the model catalog has been fetched, the list is filtered to models that actually exist in the catalog; before any fetch it renders as static suggestions. Each entry offers a one-click "add prefix" action that derives the provider prefix from the model ID (`deepseek/deepseek-chat` → `deepseek/`).
- Full model discovery is a client-side searchable list (`OpenRouterModelBrowser`) over the existing `GET /api/openrouter-sidecar/models` response. No server-side search endpoint is added; the catalog is small enough to filter in the browser.
- The models query only runs when the sidecar is enabled and an API key is configured, so a fresh settings page with no key does not issue doomed model requests.

## Failure modes

- No API key or sidecar disabled: model browser shows an instructive empty state ("save API key and test connection"); popular models render with a verification note.
- Empty search result: explicit "No models match your search" row instead of a blank panel.
