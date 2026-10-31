import { useCallback, useMemo, useState } from "react";
import { ChevronsUpDown, X } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import type { ModelListScope } from "@/features/api-keys/api";
import { useModels } from "@/features/api-keys/hooks/use-models";
import type { ModelItem } from "@/features/api-keys/schemas";

export type ModelMultiSelectProps = {
  value: string[];
  onChange: (value: string[]) => void;
  placeholder?: string;
  /** Limit rules pass ``subscriptions``; other pickers keep the full catalog. */
  scope?: ModelListScope;
};

export function ModelMultiSelect({
  value,
  onChange,
  placeholder,
  scope,
}: ModelMultiSelectProps) {
  const { t } = useTranslation();
  const placeholderLabel = placeholder ?? t("apiKeys.modelSelect.all");
  const { data: models = [], isLoading } = useModels(scope);
  const [search, setSearch] = useState("");

  const options = useMemo(() => {
    const known = new Set(models.map((model) => model.id));
    const saved: ModelItem[] = [];
    for (const id of value) {
      if (known.has(id)) continue;
      saved.push({
        id,
        name: id,
        sourceOnly: false,
        supportedReasoningEfforts: [],
      });
    }
    return [...saved, ...models];
  }, [models, value]);

  const filtered = useMemo(() => {
    if (!search.trim()) return options;
    const q = search.toLowerCase();
    return options.filter(
      (m) => m.id.toLowerCase().includes(q) || m.name.toLowerCase().includes(q),
    );
  }, [options, search]);

  const selectedSet = useMemo(() => new Set(value), [value]);

  const toggle = useCallback(
    (modelId: string) => {
      if (selectedSet.has(modelId)) {
        onChange(value.filter((v) => v !== modelId));
      } else {
        onChange([...value, modelId]);
      }
    },
    [selectedSet, value, onChange],
  );

  const remove = useCallback(
    (modelId: string) => {
      onChange(value.filter((v) => v !== modelId));
    },
    [value, onChange],
  );

  const selectAll = useCallback(() => {
    onChange([]);
  }, [onChange]);

  const label =
    value.length === 0 ? placeholderLabel : t("apiKeys.modelSelect.selected", { count: value.length });

  return (
    <div className="space-y-1.5">
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            type="button"
            variant="outline"
            className="w-full justify-between font-normal"
            disabled={isLoading}
          >
            <span className="truncate text-left">{isLoading ? t("apiKeys.modelSelect.loading") : label}</span>
            <ChevronsUpDown className="ml-1 size-4 shrink-0 opacity-50" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start" className="w-[var(--radix-dropdown-menu-trigger-width)] max-h-64">
          <div className="px-2 py-1.5">
            <Input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder={t("apiKeys.modelSelect.search")}
              className="h-7 text-xs"
              onClick={(e) => e.stopPropagation()}
              onKeyDown={(e) => e.stopPropagation()}
            />
          </div>
          <DropdownMenuSeparator />
          <DropdownMenuCheckboxItem
            checked={value.length === 0}
            onCheckedChange={selectAll}
            onSelect={(e) => e.preventDefault()}
          >
            {t("apiKeys.modelSelect.all")}
          </DropdownMenuCheckboxItem>
          <DropdownMenuSeparator />
          {filtered.map((model) => (
            <DropdownMenuCheckboxItem
              key={model.id}
              checked={selectedSet.has(model.id)}
              onCheckedChange={() => toggle(model.id)}
              onSelect={(e) => e.preventDefault()}
            >
              <span className="flex min-w-0 flex-col">
                <span className="truncate">{model.name || model.id}</span>
                {model.name && model.name !== model.id ? (
                  <span className="truncate font-mono text-[10px] text-muted-foreground">{model.id}</span>
                ) : null}
              </span>
            </DropdownMenuCheckboxItem>
          ))}
          {filtered.length === 0 ? (
            <div className="px-2 py-1.5 text-xs text-muted-foreground">{t("apiKeys.modelSelect.empty")}</div>
          ) : null}
        </DropdownMenuContent>
      </DropdownMenu>

      {value.length > 0 ? (
        <div className="flex flex-wrap gap-1">
          {value.map((modelId) => (
            <Badge key={modelId} variant="secondary" className="gap-1 text-xs">
              {modelId}
              <button
                type="button"
                className="hover:text-foreground ml-0.5"
                onClick={() => remove(modelId)}
              >
                <X className="size-3" />
              </button>
            </Badge>
          ))}
        </div>
      ) : null}
    </div>
  );
}
