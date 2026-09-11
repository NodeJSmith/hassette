import { useAppStore } from "../../state/store";
import { AlertShell } from "../shared/alert-shell";
import { AppLink } from "../shared/app-link";
import { IconWarning } from "../shared/icons";

interface FailedApp {
  app_key: string;
  error_message: string | null;
}

interface AlertBannerProps {
  failedApps: FailedApp[];
}

/**
 * Failed-apps notice. Stays hand-rolled rather than using `AlertShell`: it borders with
 * `border-destructive` (full-strength `--err`), while the shell's `danger` tone borders with
 * `--destructive-border` (`--err` at 30% alpha). Only `tone` selects that token and callers are
 * told not to override it via `className`, so the shell has no way to render this border. The
 * container shape also differs (`mx-8`, stacked `flex-col`, tighter `px-3 py-2`), though that
 * part `className` could express.
 */
export function AlertBanner({ failedApps }: AlertBannerProps) {
  if (failedApps.length === 0) return null;

  return (
    <div
      className="mx-8 mb-2 flex flex-col items-stretch gap-2 rounded-md border border-destructive bg-[var(--destructive-bg)] px-3 py-2 text-sm text-destructive"
      role="alert"
      data-testid="alert-banner"
    >
      <strong>
        {failedApps.length} app{failedApps.length > 1 ? "s" : ""} failed
      </strong>
      <ul className="mt-1 flex list-none flex-col gap-1 p-0">
        {failedApps.map((app) => (
          <li key={app.app_key} className="text-sm">
            <AppLink appKey={app.app_key} />
            {app.error_message && <span className="text-muted-foreground"> — {app.error_message}</span>}
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Warns when telemetry is degraded — queue overflow, backpressure, or an unreachable database. */
export function TelemetryDegradedBanner() {
  const telemetryDegraded = useAppStore((s) => s.telemetryDegraded);
  const droppedOverflow = useAppStore((s) => s.droppedOverflow);
  const droppedExhausted = useAppStore((s) => s.droppedExhausted);

  if (!telemetryDegraded) return null;

  const totalDropped = droppedOverflow + droppedExhausted;

  return (
    <AlertShell
      tone="warning"
      className="flex items-center gap-3 text-[var(--status-warning)]"
      role="alert"
      data-testid="telemetry-degraded-banner"
    >
      <IconWarning />
      <span className="flex-1 leading-[var(--text-body-leading)]">
        Telemetry is degraded
        {totalDropped > 0 ? ` — ${totalDropped} events dropped` : ""}. Some data may be missing.
      </span>
    </AlertShell>
  );
}
