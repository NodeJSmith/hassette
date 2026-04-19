/**
 * FrameworkHealth — System Health summary badge for the dashboard.
 *
 * Derives framework error count from the already-fetched error feed data,
 * ensuring the badge and feed always show coherent counts.
 */

import type { DashboardErrorEntry } from "../../api/endpoints";
import { IconWarning, IconCheck } from "../shared/icons";

interface Props {
  errors: DashboardErrorEntry[] | null;
  loading: boolean;
  hasError: boolean;
}

export function FrameworkHealth({ errors, loading, hasError }: Props) {
  const totalFrameworkErrors = errors
    ? errors.filter((e) => e.source_tier === "framework").length
    : 0;
  const hasErrors = totalFrameworkErrors > 0;

  const badgeVariant = loading || hasError ? "neutral" : hasErrors ? "danger" : "success";
  const badgeText = loading ? "…" : hasError ? "?" : String(totalFrameworkErrors);
  const icon = loading || hasError ? <IconWarning /> : hasErrors ? <IconWarning /> : <IconCheck />;

  return (
    <div class="ht-card ht-card--receded" data-testid="framework-health">
      <div class="ht-framework-health__title">
        {icon}
        <span class="ht-heading-5" style={{ margin: 0 }}>System Health</span>
        <span
          class={`ht-badge ht-badge--${badgeVariant} ht-badge--sm`}
          data-testid="framework-error-count"
          aria-label={
            loading ? "Loading framework health"
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
