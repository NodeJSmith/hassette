import type { DashboardErrorEntry } from "../../api/endpoints";
import { useRelativeTime } from "../../hooks/use-relative-time";

interface Props {
  errors: DashboardErrorEntry[] | null;
}

export function ErrorFeed({ errors }: Props) {
  if (!errors || errors.length === 0) {
    return <p class="ht-text-muted ht-text-xs">No recent errors. All systems healthy.</p>;
  }

  return (
    <div class="ht-error-feed" data-testid="dashboard-errors">
      {errors.map((err) => (
        <ErrorEntry key={`${err.timestamp}-${err.app_key}`} err={err} />
      ))}
    </div>
  );
}

function ErrorEntry({ err }: { err: DashboardErrorEntry }) {
  const relativeTime = useRelativeTime(err.timestamp);

  return (
    <div class="ht-error-entry" data-testid="error-item">
      <div class="ht-error-entry__header">
        <span class={`ht-tag ht-tag--${err.kind}`}>{err.kind}</span>
        <a href={`/apps/${err.app_key}`} class="ht-text-sm">
          {err.app_key}
        </a>
        <span class="ht-text-secondary ht-text-xs">
          {relativeTime}
        </span>
      </div>
      <div class="ht-error-entry__body">
        <code class="ht-text-sm">{err.error_type}</code>
        <span class="ht-text-sm">{err.error_message}</span>
      </div>
    </div>
  );
}
