import clsx from "clsx";

import { useAppState } from "../../state/context";
import { AppLink } from "../shared/app-link";
import { IconWarning } from "../shared/icons";
import styles from "./alert-banner.module.css";

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
    <div class={clsx(styles.alert, styles.alertDanger)} role="alert" data-testid="alert-banner">
      <strong>
        {failedApps.length} app{failedApps.length > 1 ? "s" : ""} failed
      </strong>
      <ul class={styles.alertList}>
        {failedApps.map((app) => (
          <li key={app.app_key}>
            <AppLink appKey={app.app_key} />
            {app.error_message && <span class="ht-text-secondary"> — {app.error_message}</span>}
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
  const { telemetryDegraded, droppedOverflow, droppedExhausted } = useAppState();

  if (!telemetryDegraded.value) return null;

  const totalDropped = droppedOverflow.value + droppedExhausted.value;

  return (
    <div
      class={clsx(styles.degradedBanner, styles.degradedBannerWarn)}
      data-testid="telemetry-degraded-banner"
      role="alert"
    >
      <IconWarning />
      <span class={styles.degradedBannerText}>
        Telemetry is degraded
        {totalDropped > 0 ? ` — ${totalDropped} events dropped` : ""}. Some data may be missing.
      </span>
    </div>
  );
}
