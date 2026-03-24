import type { DashboardErrorEntry } from "../../api/endpoints";
import { useRelativeTime } from "../../hooks/use-relative-time";

interface Props {
  errors: DashboardErrorEntry[] | null;
}

const KNOWN_KINDS = new Set(["handler", "job"]);

function shortErrorType(t: string): string {
  if (!t) return "";
  const lastDot = t.lastIndexOf(".");
  return lastDot === -1 ? t : t.substring(lastDot + 1);
}

function kindClass(kind: string): string {
  return KNOWN_KINDS.has(kind) ? kind : "neutral";
}

function errorEntryKey(err: DashboardErrorEntry): string {
  const id = err.listener_id ?? err.job_id ?? err.timestamp;
  return `${err.kind}-${id}-${err.app_key}-${err.error_type}`;
}

export function ErrorFeed({ errors }: Props) {
  if (!errors || errors.length === 0) {
    return <p class="ht-text-muted ht-text-xs">No recent errors. All systems healthy.</p>;
  }

  return (
    <div class="ht-error-feed" data-testid="dashboard-errors">
      {errors.map((err) => (
        <ErrorEntry key={errorEntryKey(err)} err={err} />
      ))}
    </div>
  );
}

function ErrorEntry({ err }: { err: DashboardErrorEntry }) {
  const relativeTime = useRelativeTime(err.timestamp);
  const badgeText = shortErrorType(err.error_type) || err.kind;
  const subtitle = err.handler_method || err.job_name;

  return (
    <div class="ht-error-entry" data-testid="error-item">
      <div class="ht-error-entry__header">
        <span
          class={`ht-tag ht-tag--${kindClass(err.kind)}`}
          style="max-width:140px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;display:inline-block"
        >
          {badgeText}
        </span>
        <a href={`/apps/${err.app_key}`} class="ht-text-sm">
          {err.app_key}
        </a>
        {subtitle && (
          <>
            {" · "}
            <span class="ht-text-mono ht-text-xs">{subtitle}</span>
          </>
        )}
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
