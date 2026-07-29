import { cn } from "@/lib/utils";

import { useAppStore } from "../../state/store";
import { AppLink } from "../shared/app-link";
import { IconWarning } from "../shared/icons";

interface FailedApp {
  app_key: string;
  error_message: string | null;
}

interface AlertBannerProps {
  failedApps: FailedApp[];
}

export function AlertBanner({ failedApps }: AlertBannerProps) {
  if (failedApps.length === 0) return null;

  return (
    <div
      className={cn(
        "mx-8 mb-2 flex flex-col items-stretch gap-2 rounded-md border border-destructive bg-[var(--destructive-bg)] px-3 py-2 text-sm text-destructive",
      )}
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

/**
 * TelemetryDegradedBanner renders an amber warning banner when the telemetry
 * database is degraded (queue overflow, backpressure, or unreachable).
 * Reads `telemetryDegraded`, `droppedOverflow`, and `droppedExhausted` signals.
 */
export function TelemetryDegradedBanner() {
  const telemetryDegraded = useAppStore((s) => s.telemetryDegraded);
  const droppedOverflow = useAppStore((s) => s.droppedOverflow);
  const droppedExhausted = useAppStore((s) => s.droppedExhausted);

  if (!telemetryDegraded) return null;

  const totalDropped = droppedOverflow + droppedExhausted;

  return (
    <div
      className="mb-4 flex items-center gap-3 rounded-md border border-[var(--status-warning)] bg-[var(--status-warning-bg)] px-4 py-3 text-[length:var(--text-body)] text-[var(--status-warning)]"
      data-testid="telemetry-degraded-banner"
      role="alert"
    >
      <IconWarning />
      <span className="flex-1 text-[length:var(--text-body)] leading-[var(--text-body-leading)]">
        Telemetry is degraded
        {totalDropped > 0 ? ` — ${totalDropped} events dropped` : ""}. Some data may be missing.
      </span>
    </div>
  );
}
