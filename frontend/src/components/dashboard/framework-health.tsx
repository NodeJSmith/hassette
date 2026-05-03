/**
 * FrameworkHealth — System Health summary badge for the dashboard.
 *
 * Shows framework-tier error count via the dedicated framework-summary endpoint,
 * which runs a COUNT(*) query without the feed's LIMIT cap. When errors exist,
 * a toggle reveals a collapsible detail section.
 */

import { useSignal } from "@preact/signals";
import { getFrameworkSummary } from "../../api/endpoints";
import { useScopedApi } from "../../hooks/use-scoped-api";
import { IconWarning, IconCheck } from "../shared/icons";

export function FrameworkHealth() {
  const fwSummary = useScopedApi((since) => getFrameworkSummary(since));
  const expanded = useSignal(false);

  const isLoading = fwSummary.loading.value;
  const hasError = !!fwSummary.error.value;
  const errorCount = fwSummary.data.value?.total_errors ?? 0;
  const jobErrorCount = fwSummary.data.value?.total_job_errors ?? 0;
  const totalFrameworkErrors = errorCount + jobErrorCount;
  const hasErrors = totalFrameworkErrors > 0;

  const badgeVariant = isLoading || hasError ? "neutral" : hasErrors ? "danger" : "success";
  const badgeText = isLoading ? "…" : hasError ? "?" : String(totalFrameworkErrors);
  const icon = isLoading || hasError ? <IconWarning /> : hasErrors ? <IconWarning /> : <IconCheck />;

  return (
    <div class="ht-card ht-card--receded" data-testid="framework-health">
      <div class="ht-framework-health__title">
        {icon}
        <span class="ht-heading-5" style={{ margin: 0 }}>System Health</span>
        <span
          class={`ht-badge ht-badge--${badgeVariant} ht-badge--sm`}
          data-testid="framework-error-count"
          aria-label={
            isLoading ? "Loading framework health"
              : hasError ? "Failed to load framework health"
                : `${totalFrameworkErrors} framework error${totalFrameworkErrors !== 1 ? "s" : ""}`
          }
        >
          {badgeText}
        </span>
        {hasErrors && !isLoading && !hasError && (
          <button
            type="button"
            class="ht-btn ht-btn--xs ht-btn--ghost ht-framework-health__toggle"
            onClick={() => { expanded.value = !expanded.value; }}
            aria-expanded={expanded.value}
            aria-controls="framework-health-detail"
          >
            {expanded.value ? "Hide details" : "Details"}
          </button>
        )}
      </div>
      {hasErrors && expanded.value && (
        <div id="framework-health-detail" class="ht-framework-health__body">
          <p class="ht-text-xs ht-text-muted">
            {errorCount > 0 && `${errorCount} handler error${errorCount !== 1 ? "s" : ""}`}
            {errorCount > 0 && jobErrorCount > 0 && ", "}
            {jobErrorCount > 0 && `${jobErrorCount} job error${jobErrorCount !== 1 ? "s" : ""}`}
            {" "}in the selected time window.
          </p>
        </div>
      )}
    </div>
  );
}
