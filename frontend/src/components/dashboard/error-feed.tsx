import type { DashboardErrorEntry } from "../../api/endpoints";
import { useRelativeTime } from "../../hooks/use-relative-time";

interface Props {
  errors: DashboardErrorEntry[] | null;
}

const KNOWN_KINDS = new Set(["handler", "job"]);

function shortErrorType(t: string | null): string {
  if (!t) return "";
  const lastDot = t.lastIndexOf(".");
  return lastDot === -1 ? t : t.substring(lastDot + 1);
}

function kindClass(kind: string): string {
  return KNOWN_KINDS.has(kind) ? kind : "neutral";
}

function errorEntryKey(err: DashboardErrorEntry, index: number): string {
  // listener_id/job_id can be 0 or null (sentinel/orphan) — treat as missing
  const rawId = err.kind === "handler" ? err.listener_id : err.job_id;
  const id = rawId || `${err.execution_start_ts}-${index}`;
  return `${err.kind}-${id}-${err.app_key ?? "orphan"}`;
}

export function ErrorFeed({ errors }: Props) {
  if (!errors || errors.length === 0) {
    return <p class="ht-text-muted ht-text-xs">No recent errors. All systems healthy.</p>;
  }

  return (
    <div class="ht-error-feed" data-testid="dashboard-errors">
      {errors.map((err, i) => (
        <ErrorEntry key={errorEntryKey(err, i)} err={err} />
      ))}
    </div>
  );
}

function ErrorEntry({ err }: { err: DashboardErrorEntry }) {
  const relativeTime = useRelativeTime(err.execution_start_ts);
  const badgeText = shortErrorType(err.error_type) || err.kind;

  // Orphan detection: null listener_id or job_id means the handler/job was deleted
  const isOrphan = err.kind === "handler" ? err.listener_id === null : err.job_id === null;
  const rawSubtitle = err.kind === "handler" ? err.handler_method : err.job_name;
  const subtitle = isOrphan
    ? (err.kind === "handler" ? "deleted handler" : "deleted job")
    : rawSubtitle;

  const appDisplay = err.app_key ?? (err.kind === "handler" ? "deleted handler" : "deleted job");
  const isFramework = err.source_tier === "framework";

  return (
    <div class="ht-error-entry" data-testid="error-item">
      <div class="ht-error-entry__header">
        <span
          class={`ht-tag ht-tag--${kindClass(err.kind)} ht-tag--truncated`}
        >
          {badgeText}
        </span>
        {isFramework && (
          <span class="ht-tag ht-tag--framework ht-tag--xs">Framework</span>
        )}
        {err.app_key ? (
          <a href={`/apps/${err.app_key}`} class="ht-text-sm">
            {err.app_key}
          </a>
        ) : (
          <span class="ht-text-sm ht-text-muted">{appDisplay}</span>
        )}
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
