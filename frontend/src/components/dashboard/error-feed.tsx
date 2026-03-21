import type { DashboardErrorEntry } from "../../api/endpoints";
import { formatRelativeTime } from "../../utils/format";

interface Props {
  errors: DashboardErrorEntry[] | null;
}

export function ErrorFeed({ errors }: Props) {
  if (!errors || errors.length === 0) {
    return <p class="ht-text-secondary ht-text-sm">No recent errors.</p>;
  }

  return (
    <div class="ht-error-feed">
      {errors.map((err, i) => (
        <div key={i} class="ht-error-entry">
          <div class="ht-error-entry-header">
            <span class={`ht-tag ht-tag-${err.kind}`}>{err.kind}</span>
            <a href={`/apps/${err.app_key}`} class="ht-text-sm">
              {err.app_key}
            </a>
            <span class="ht-text-secondary ht-text-xs">
              {formatRelativeTime(err.timestamp)}
            </span>
          </div>
          <div class="ht-error-entry-body">
            <code class="ht-text-sm">{err.error_type}</code>
            <span class="ht-text-sm">{err.error_message}</span>
          </div>
        </div>
      ))}
    </div>
  );
}
