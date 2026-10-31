import { useQuery } from "@tanstack/react-query";

import { listModels, type ModelListScope } from "@/features/api-keys/api";

export type { ModelItem } from "@/features/api-keys/schemas";

export function useModels(scope?: ModelListScope) {
  return useQuery({
    queryKey: scope == null ? ["models"] : ["models", scope],
    queryFn: () => listModels(scope),
    staleTime: 5 * 60 * 1000,
    select: (data) => data.models,
  });
}
