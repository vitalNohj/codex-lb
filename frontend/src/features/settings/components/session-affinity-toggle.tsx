import { Switch } from "@/components/ui/switch";

type SessionAffinityToggleProps = {
  checked: boolean;
  disabled: boolean;
  onCheckedChange: (checked: boolean) => void;
};

export function SessionAffinityToggle({ checked, disabled, onCheckedChange }: SessionAffinityToggleProps) {
  return (
    <div className="space-y-1.5">
      <label
        className="flex items-center justify-between gap-3 text-sm font-medium"
        htmlFor="claude-sidecar-session-affinity"
      >
        Session affinity
        <Switch
          id="claude-sidecar-session-affinity"
          checked={checked}
          disabled={disabled}
          onCheckedChange={onCheckedChange}
        />
      </label>
      <p className="text-[13px] leading-relaxed text-muted-foreground">
        Keeps one chat on the same CLIProxyAPI account. New chats still follow the routing strategy.
      </p>
    </div>
  );
}
