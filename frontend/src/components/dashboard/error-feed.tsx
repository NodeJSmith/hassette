import { useSignal } from "@preact/signals";
import type { DashboardErrorEntry } from "../../api/endpoints";
import { ErrorCell } from "../app-detail/error-cell";
import { useRelativeTime } from "../../hooks/use-relative-time";
import { isFrameworkKey, frameworkDisplayLabel } from "../../utils/framework-keys";

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
  const tracebackExpanded = useSignal(false);

  const isFramework = isFrameworkKey(err.app_key);
  const isOrphan = !isFramework && (err.kind === "handler" ? err.listener_id === null : err.job_id === null);
  const rawSubtitle = err.kind === "handler" ? err.handler_method : err.job_name;
  const isUnregisteredFramework = isFramework && (err.kind === "handler" ? err.listener_id === null : err.job_id === null);
  const subtitle = isOrphan
    ? (err.kind === "handler" ? "deleted handler" : "deleted job")
    : isUnregisteredFramework
      ? `${rawSubtitle} (unregistered)`
      : rawSubtitle;

  // Use source_tier to determine if this is a framework error (badge display)
  const isFrameworkTier = err.source_tier === "framework";
  const appDisplay = isFramework
    ? frameworkDisplayLabel(err.app_key as string)
    : (err.app_key ?? (err.kind === "handler" ? "deleted handler" : "deleted job"));

  return (
    <div class="ht-error-entry" data-testid="error-item">
      <div class="ht-error-entry__header">
        <span
          class={`ht-tag ht-tag--${kindClass(err.kind)} ht-tag--truncated`}
        >
          {badgeText}
        </span>
        {isFrameworkTier && (
          <span class="ht-tag ht-tag--framework ht-tag--xs">Framework</span>
        )}
        {!isFramework && err.app_key ? (
          <a href={`/apps/${err.app_key}`} class="ht-text-sm">{appDisplay}</a>
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
        <ErrorCell
          traceback={err.error_traceback}
          message={err.error_message}
          expanded={tracebackExpanded.value}
          onToggle={() => { tracebackExpanded.value = !tracebackExpanded.value; }}
        />
        {tracebackExpanded.value && err.error_traceback && (
          <pre class="ht-traceback">{err.error_traceback}</pre>
        )}
      </div>
    </div>
  );
}
