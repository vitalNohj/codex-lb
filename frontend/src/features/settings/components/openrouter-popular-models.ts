export const POPULAR_OPENROUTER_MODELS: readonly string[] = [
  "deepseek/deepseek-chat",
  "google/gemini-2.5-pro-preview",
  "anthropic/claude-sonnet-4",
  "meta-llama/llama-3.3-70b-instruct",
  "qwen/qwen-2.5-72b-instruct",
  "openai/gpt-4o-mini",
  "mistralai/mistral-large",
  "cohere/command-r-plus",
];

export function prefixFromModelId(id: string): string {
  const slashIndex = id.indexOf("/");
  if (slashIndex < 0) {
    return id;
  }
  return id.slice(0, slashIndex + 1);
}
