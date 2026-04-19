/**
 * FrameworkHealth — System Health summary badge for the dashboard.
 *
 * Shows framework-tier error count via source_tier=framework query.
 * Does not expand — the unified Recent Errors feed shows all errors including framework.
 */

import { getFrameworkSummary } from "../../api/endpoints";
import { useScopedApi } from "../../hooks/use-scoped-api";
import { IconWarning, IconCheck } from "../shared/icons";

export function FrameworkHealth() {
  const fwSummary = useScopedApi((sid) => getFrameworkSummary(sid));

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
      </div>
    </div>
  );
}
