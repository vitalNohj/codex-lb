import { Switch } from "@/components/ui/switch";

type SessionAffinityToggleProps = {
  checked: boolean;
  disabled: boolean;
  onCheckedChange: (checked: boolean) => void;
  /** The state read from CLIProxyAPI; `null` while unknown. */
  enabled?: boolean | null;
};

export function SessionAffinityToggle({ checked, disabled, onCheckedChange, enabled = null }: SessionAffinityToggleProps) {
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
        Keeps one chat on the same CLIProxyAPI account; new chats still follow the routing strategy.
        Applies to every account (<code className="font-mono text-[12px]">routing.session-affinity</code>).
      </p>
      {enabled === false ? (
        <p role="alert" className="text-[13px] leading-relaxed text-amber-600 dark:text-amber-400">
          Session affinity is off. A chat codex-lb cannot pin to an account may switch accounts on every turn and
          miss the prompt cache, which bills the whole conversation again. Keep it on.
        </p>
      ) : null}
    </div>
  );
}
