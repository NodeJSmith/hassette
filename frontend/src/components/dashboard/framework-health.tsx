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

  const errorCount = fwSummary.data.value?.total_errors ?? 0;
  const jobErrorCount = fwSummary.data.value?.total_job_errors ?? 0;
  const totalFrameworkErrors = errorCount + jobErrorCount;
  const hasErrors = totalFrameworkErrors > 0;

  return (
    <div class="ht-card ht-card--receded" data-testid="framework-health">
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
    </div>
  );
}
