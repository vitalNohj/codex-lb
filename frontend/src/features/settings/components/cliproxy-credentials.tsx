import { Badge } from "@/components/ui/badge";
import { useCliproxyCredentials } from "@/features/settings/hooks/use-settings";
import type { CliproxyCredential } from "@/features/settings/schemas";

const HEALTH_LABELS: Record<string, string> = {
  active: "Healthy",
  paused: "Paused",
  reauth_required: "Re-auth required",
  quota_exceeded: "Quota exceeded",
  unavailable: "Unavailable",
  rate_limited: "Rate limited",
};

function healthLabel(health: string): string {
  return HEALTH_LABELS[health] ?? health;
}

function healthVariant(health: string): "secondary" | "outline" | "destructive" {
  if (health === "reauth_required" || health === "quota_exceeded" || health === "unavailable") {
    return "destructive";
  }
  if (health === "paused" || health === "rate_limited") {
    return "outline";
  }
  return "secondary";
}

function CredentialRow({ credential }: { credential: CliproxyCredential }) {
  const label = credential.email || credential.name;
  return (
    <article
      className="space-y-2 rounded-md border bg-card px-3 py-2.5"
      aria-label={`${credential.provider} credential ${label}`}
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="truncate text-sm font-medium">{label}</p>
          <p className="truncate font-mono text-xs text-muted-foreground">{credential.name}</p>
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          <Badge variant="outline">{credential.provider}</Badge>
          <Badge variant={healthVariant(credential.health)}>{healthLabel(credential.health)}</Badge>
        </div>
      </div>
      {credential.prefix ? (
        <p className="font-mono text-xs text-muted-foreground">prefix {credential.prefix}</p>
      ) : null}
      {credential.models.length > 0 ? (
        <ul className="flex flex-wrap gap-1.5" aria-label={`Models for ${label}`}>
          {credential.models.map((model) => (
            <li key={model}>
              <Badge variant="secondary">{model}</Badge>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-[13px] text-muted-foreground">
          {credential.modelsError ?? "No models reported for this credential."}
        </p>
      )}
    </article>
  );
}

export function CliproxyCredentials({ enabled }: { enabled: boolean }) {
  const { credentialsQuery } = useCliproxyCredentials(enabled);

  if (!enabled) {
    return (
      <p className="text-sm text-muted-foreground">
        Add a management key to list CLIProxyAPI credentials. Tokens stay on the sidecar and are not shown here.
      </p>
    );
  }

  if (credentialsQuery.isLoading) {
    return <p className="text-sm text-muted-foreground">Loading credentials...</p>;
  }

  if (credentialsQuery.isError) {
    return <p className="text-sm text-destructive">Could not load CLIProxyAPI credentials.</p>;
  }

  const payload = credentialsQuery.data;
  if (!payload || payload.status !== "healthy") {
    return <p className="text-sm text-muted-foreground">{payload?.message ?? "CLIProxyAPI credentials are unavailable."}</p>;
  }

  const credentials = payload.providers.flatMap((group) => group.credentials);
  if (credentials.length === 0) {
    return <p className="text-sm text-muted-foreground">No CLIProxyAPI credentials.</p>;
  }

  return (
    <div className="@container grid gap-2 @3xl:grid-cols-2">
      {credentials.map((credential) => (
        <CredentialRow
          key={`${credential.provider}:${credential.authIndex ?? credential.name}`}
          credential={credential}
        />
      ))}
    </div>
  );
}
