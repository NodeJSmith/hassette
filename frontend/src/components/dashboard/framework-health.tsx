/**
 * FrameworkHealth — System Health affordance for the dashboard.
 *
 * Always visible, regardless of whether framework errors exist.
 * Shows framework-tier error count and KPIs via source_tier=framework queries.
 * Expands to show framework error feed on click.
 */

import { useSignal } from "@preact/signals";
import { getFrameworkSummary } from "../../api/endpoints";
import { useScopedApi } from "../../hooks/use-scoped-api";
import { ErrorFeed } from "./error-feed";
import { IconWarning, IconCheck } from "../shared/icons";

interface ChevronProps {
  open: boolean;
}

function Chevron({ open }: ChevronProps) {
  return (
    <svg
      class="ht-icon-svg"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      stroke-width="2"
      stroke-linecap="round"
      stroke-linejoin="round"
      aria-hidden="true"
      style={{ transform: open ? "rotate(180deg)" : "rotate(0deg)", transition: "transform 0.15s" }}
    >
      <path d="m6 9 6 6 6-6" />
    </svg>
  );
}

export function FrameworkHealth() {
  const expanded = useSignal(false);

  const fwSummary = useScopedApi((sid) => getFrameworkSummary(sid));

  const errorCount = fwSummary.data.value?.total_errors ?? 0;
  const jobErrorCount = fwSummary.data.value?.total_job_errors ?? 0;
  const totalFrameworkErrors = errorCount + jobErrorCount;
  const hasErrors = totalFrameworkErrors > 0;

  const handleToggle = () => {
    expanded.value = !expanded.value;
  };

  const handleKeyDown = (e: KeyboardEvent) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      expanded.value = !expanded.value;
    }
  };

  return (
    <div class="ht-card ht-card--receded" data-testid="framework-health">
      <div
        class="ht-framework-health__header"
        role="button"
        tabIndex={0}
        aria-expanded={expanded.value}
        aria-controls="framework-health-body"
        onClick={handleToggle}
        onKeyDown={handleKeyDown}
      >
        <div class="ht-framework-health__title">
          {hasErrors ? <IconWarning /> : <IconCheck />}
          <span class="ht-heading-5" style={{ margin: 0 }}>System Health</span>
          <span
            class={`ht-badge ht-badge--${hasErrors ? "danger" : "success"} ht-badge--sm`}
            data-testid="framework-error-count"
            aria-label={`${totalFrameworkErrors} framework error${totalFrameworkErrors !== 1 ? "s" : ""}`}
          >
            {totalFrameworkErrors}
          </span>
        </div>
        <Chevron open={expanded.value} />
      </div>

      {expanded.value && (
        <div id="framework-health-body" class="ht-framework-health__body">
          {fwSummary.loading.value ? (
            <p class="ht-text-muted ht-text-xs">Loading framework telemetry…</p>
          ) : fwSummary.error.value ? (
            <p class="ht-text-danger ht-text-xs">Failed to load framework errors: {fwSummary.error.value}</p>
          ) : (
            <ErrorFeed errors={fwSummary.data.value?.errors ?? null} />
          )}
        </div>
      )}
    </div>
  );
}
