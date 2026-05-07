/**
 * ServiceStatusPanel — displays degraded internal service statuses on the dashboard.
 *
 * Subscribes to the global serviceStatus signal (populated from WebSocket
 * service_status messages). Shows services that need attention:
 *   - RUNNING but not ready: amber "Starting" row with optional phase detail text
 *   - EXHAUSTED_DEAD: permanent failure indicator (red/danger)
 *   - EXHAUSTED_COOLING: countdown timer until next retry (amber/warning)
 *   - FAILED / CRASHED: active failure
 * Services that are running and ready, or in other healthy statuses, are hidden.
 */

import { useEffect, useRef, useState } from "preact/hooks";
import { useAppState } from "../../state/context";
import type { ServiceStatusEntry } from "../../state/create-app-state";
import { readinessVariant, statusToKind } from "../../utils/status";
import { StatusShape } from "../shared/status-shape";

const HEALTHY_STATUSES = new Set(["running", "starting", "not_started", "stopping", "stopped"]);

function formatCountdown(secondsRemaining: number): string {
  const s = Math.max(0, Math.floor(secondsRemaining));
  if (s >= 60) {
    const m = Math.floor(s / 60);
    const rem = s % 60;
    return rem > 0 ? `${m}m ${rem}s` : `${m}m`;
  }
  return `${s}s`;
}

interface CountdownTimerProps {
  retryAt: number;
}

function CountdownTimer({ retryAt }: CountdownTimerProps) {
  const [secondsLeft, setSecondsLeft] = useState<number>(() =>
    Math.max(0, retryAt - Date.now() / 1000),
  );
  const rafRef = useRef<number | null>(null);
  const lastSecRef = useRef<number>(Math.floor(secondsLeft));

  useEffect(() => {
    function tick() {
      const remaining = Math.max(0, retryAt - Date.now() / 1000);
      const currentSec = Math.floor(remaining);
      if (currentSec !== lastSecRef.current) {
        lastSecRef.current = currentSec;
        setSecondsLeft(remaining);
      }
      if (remaining > 0) {
        rafRef.current = requestAnimationFrame(tick);
      }
    }
    rafRef.current = requestAnimationFrame(tick);
    return () => {
      if (rafRef.current !== null) {
        cancelAnimationFrame(rafRef.current);
      }
    };
  }, [retryAt]);

  if (secondsLeft <= 0) {
    return <span class="ht-ssp__detail ht-ssp__detail--cooling">retrying now…</span>;
  }
  return (
    <span class="ht-ssp__detail ht-ssp__detail--cooling" aria-label={`Retrying in ${formatCountdown(secondsLeft)}`}>
      Retrying in {formatCountdown(secondsLeft)}
    </span>
  );
}

const STATUS_LABELS: Record<string, string> = {
  exhausted_dead: "Permanently failed",
  exhausted_cooling: "Cooling down",
  failed: "Failed",
  crashed: "Crashed",
  running_not_ready: "Starting",
};

interface ServiceRowProps {
  entry: ServiceStatusEntry;
}

function ServiceRow({ entry }: ServiceRowProps) {
  const { status, resource_name, retry_at, ready, ready_phase } = entry;
  const isStarting = status === "running" && !ready;
  const variant = readinessVariant(status, ready);
  const label = isStarting ? STATUS_LABELS["running_not_ready"] : (STATUS_LABELS[status] ?? status);

  // Use StatusShape for the status indicator instead of dot spans
  const shapeKind = statusToKind(isStarting ? "starting" : status);

  return (
    <li class={`ht-ssp__row ht-ssp__row--${variant}`} data-testid={`service-status-row-${resource_name}`}>
      <StatusShape kind={shapeKind} size={10} />
      <span class="ht-ssp__name">{resource_name}</span>
      <span class={`ht-ssp__label ht-ssp__label--${variant}`} data-testid={`service-status-label-${resource_name}`}>
        {label}
      </span>
      {status === "exhausted_cooling" && retry_at !== null && <CountdownTimer retryAt={retry_at} />}
      {isStarting && ready_phase !== null && (
        <span class="ht-ssp__detail">{ready_phase}</span>
      )}
    </li>
  );
}

export function ServiceStatusPanel() {
  const { serviceStatus } = useAppState();
  const entries = Object.values(serviceStatus.value).filter(
    (e) => !HEALTHY_STATUSES.has(e.status) || (e.status === "running" && !e.ready),
  );

  if (entries.length === 0) return null;

  return (
    <section
      class="ht-card ht-card--receded ht-mb-6 ht-ssp"
      data-testid="service-status-panel"
      aria-label="Internal service status"
    >
      <h2 class="ht-heading-5 ht-mb-3">service status</h2>
      <ul class="ht-ssp__list" aria-label="Service statuses">
        {entries.map((entry) => (
          <ServiceRow key={entry.resource_name} entry={entry} />
        ))}
      </ul>
    </section>
  );
}
