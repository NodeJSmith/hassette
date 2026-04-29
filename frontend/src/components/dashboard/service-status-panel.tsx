/**
 * ServiceStatusPanel — displays live internal service statuses on the dashboard.
 *
 * Subscribes to the global serviceStatus signal (populated from WebSocket
 * service_status messages). Shows all services with their current status,
 * with special rendering for:
 *   - EXHAUSTED_DEAD: permanent failure indicator (red/danger)
 *   - EXHAUSTED_COOLING: countdown timer until next retry (amber/warning)
 *   - All other statuses: standard StatusBadge rendering
 */

import { useEffect, useRef, useState } from "preact/hooks";
import { useAppState } from "../../state/context";
import type { ServiceStatusEntry } from "../../state/create-app-state";
import { statusToVariant } from "../../utils/status";

/**
 * Format seconds remaining into a human-readable countdown string.
 * E.g. 125 → "2m 5s", 45 → "45s", 0 → "0s"
 */
function formatCountdown(secondsRemaining: number): string {
  const s = Math.max(0, Math.floor(secondsRemaining));
  if (s >= 60) {
    const m = Math.floor(s / 60);
    const rem = s % 60;
    return rem > 0 ? `${m}m ${rem}s` : `${m}m`;
  }
  return `${s}s`;
}

/**
 * CountdownTimer renders a live countdown using requestAnimationFrame.
 * Updates every second by checking the difference between retry_at and now.
 */
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
      // Only update React state when the second changes (avoids excessive renders)
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
    return <span class="ht-service-status-panel__countdown">retrying now…</span>;
  }
  return (
    <span class="ht-service-status-panel__countdown" aria-label={`Retrying in ${formatCountdown(secondsLeft)}`}>
      Retrying in {formatCountdown(secondsLeft)}
    </span>
  );
}

interface ServiceRowProps {
  entry: ServiceStatusEntry;
}

function ServiceRow({ entry }: ServiceRowProps) {
  const { status, resource_name, retry_at } = entry;
  const isExhaustedDead = status === "exhausted_dead";
  const isExhaustedCooling = status === "exhausted_cooling";

  if (isExhaustedDead) {
    return (
      <li
        class="ht-service-status-panel__row ht-service-status-panel__row--dead"
        data-testid={`service-status-row-${resource_name}`}
      >
        <span class="ht-service-status-panel__dot ht-service-status-panel__dot--dead" aria-hidden="true" />
        <span class="ht-service-status-panel__name">{resource_name}</span>
        <span
          class="ht-service-status-panel__label ht-service-status-panel__label--dead"
          data-testid={`service-status-label-${resource_name}`}
        >
          Permanently failed
        </span>
      </li>
    );
  }

  if (isExhaustedCooling) {
    return (
      <li
        class="ht-service-status-panel__row ht-service-status-panel__row--cooling"
        data-testid={`service-status-row-${resource_name}`}
      >
        <span class="ht-service-status-panel__dot ht-service-status-panel__dot--cooling" aria-hidden="true" />
        <span class="ht-service-status-panel__name">{resource_name}</span>
        {retry_at !== null ? (
          <CountdownTimer retryAt={retry_at} />
        ) : (
          <span
            class="ht-service-status-panel__label ht-service-status-panel__label--cooling"
            data-testid={`service-status-label-${resource_name}`}
          >
            Cooling down
          </span>
        )}
      </li>
    );
  }

  const variantClass = statusToVariant(status);

  return (
    <li
      class="ht-service-status-panel__row"
      data-testid={`service-status-row-${resource_name}`}
    >
      <span
        class={`ht-service-status-panel__dot ht-service-status-panel__dot--${variantClass}`}
        aria-hidden="true"
      />
      <span class="ht-service-status-panel__name">{resource_name}</span>
      <span
        class={`ht-service-status-panel__label ht-service-status-panel__label--${variantClass}`}
        data-testid={`service-status-label-${resource_name}`}
      >
        {status}
      </span>
    </li>
  );
}

export function ServiceStatusPanel() {
  const { serviceStatus } = useAppState();
  const entries = Object.values(serviceStatus.value);

  if (entries.length === 0) {
    return null;
  }

  const hasCritical = entries.some(
    (e) => e.status === "exhausted_dead" || e.status === "exhausted_cooling",
  );

  return (
    <div
      class={`ht-card${hasCritical ? " ht-card--urgent" : " ht-card--receded"} ht-mb-6 ht-service-status-panel`}
      data-testid="service-status-panel"
      aria-label="Internal service status"
    >
      <h2 class="ht-heading-5">Service Status</h2>
      <ul class="ht-service-status-panel__list" aria-label="Service statuses">
        {entries.map((entry) => (
          <ServiceRow key={entry.resource_name} entry={entry} />
        ))}
      </ul>
    </div>
  );
}
