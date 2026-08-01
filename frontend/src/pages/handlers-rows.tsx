import type { ReactNode } from "react";
import { Link } from "wouter";

import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

import { AppLink } from "../components/shared/app-link";
import { useRelativeTime } from "../hooks/use-relative-time";
import { handlerPath } from "../utils/app-routes";
import { formatDurationOrDash, formatRate, MS_PER_SECOND } from "../utils/format";
import type { UnifiedRow } from "../utils/handler-rows";
import { scheduleStatusLabel } from "../utils/handler-rows";

// Coarse kind labels for the table view — overview-tab-helpers uses handlerKindLabel() for richer per-listener kinds
const KIND_LABELS: Record<"listener" | "job", string> = {
  listener: "event",
  job: "job",
};

function KindBadge({ kind }: { kind: "listener" | "job" }) {
  return (
    <Badge variant={kind} size="sm">
      {KIND_LABELS[kind]}
    </Badge>
  );
}

interface MobileCardProps {
  href: string;
  appKey: string;
  name: string;
  failing?: boolean;
  "data-testid"?: string;
  metrics: ReactNode;
  footer?: ReactNode;
}

function MobileCard({ href, appKey, name, failing, metrics, footer, "data-testid": testId }: MobileCardProps) {
  return (
    <Link
      href={href}
      className={cn(
        "flex flex-col gap-1 border-b border-[var(--border-subtle)] px-4 py-3 text-inherit no-underline transition-colors last:border-b-0 hover:bg-accent max-mobile:relative max-mobile:pr-8 max-mobile:active:bg-accent max-mobile:after:absolute max-mobile:after:right-3 max-mobile:after:top-1/2 max-mobile:after:-translate-y-1/2 max-mobile:after:text-[length:var(--text-h3)] max-mobile:after:text-foreground-faint max-mobile:after:content-['›']",
        failing && "bg-[var(--destructive-bg)]",
      )}
      data-testid={testId}
    >
      <div className="flex min-w-0 flex-wrap items-baseline gap-x-2 gap-y-0.5">
        <span className="min-w-0 break-all font-mono text-sm">{appKey}</span>
        <span className="min-w-0 break-all font-mono text-sm font-semibold">{name}</span>
      </div>
      <div className="flex flex-wrap gap-x-3 gap-y-1 font-mono text-xs text-muted-foreground">{metrics}</div>
      {footer && <div className="flex gap-3 font-mono text-xs">{footer}</div>}
    </Link>
  );
}

function useHandlerRowData(row: UnifiedRow) {
  const nextRunRelative = useRelativeTime(row.next_run_ts);
  const errorRate = formatRate(row.failed, row.runs);
  const avgDuration = formatDurationOrDash(row.avg_duration_ms);
  const now = Date.now() / MS_PER_SECOND;
  const isOverdue = row.next_run_ts !== null && row.next_run_ts < now;

  let nextRunDisplay: string | null = null;
  let isScheduleStatus = false;
  if (row.next_run_ts !== null) {
    nextRunDisplay = isOverdue ? "overdue" : nextRunRelative;
  } else if (row.kind === "job") {
    nextRunDisplay = scheduleStatusLabel(row.schedule_status);
    isScheduleStatus = nextRunDisplay !== null;
  }

  return { errorRate, avgDuration, isOverdue, nextRunDisplay, isScheduleStatus };
}

interface HandlerRowProps {
  row: UnifiedRow;
}

export function HandlerTableRow({ row }: HandlerRowProps) {
  const { errorRate, avgDuration, isOverdue, nextRunDisplay } = useHandlerRowData(row);

  return (
    <tr
      className={cn(
        row.failed > 0 &&
          "bg-[var(--destructive-bg)] hover:bg-[color-mix(in_srgb,var(--destructive-bg)_70%,var(--highlight-bg))]",
      )}
      data-state={row.failed > 0 ? "failing" : "default"}
      data-testid={`${row.kind}-row-${row.id}`}
    >
      <td>
        <KindBadge kind={row.kind} />
      </td>
      <td className="font-mono text-sm">
        <AppLink appKey={row.app_key} />
      </td>
      <td className="font-mono text-sm" title={row.handler_method}>
        <AppLink appKey={row.app_key} handlerKind={row.kind} handlerId={row.handlerId}>
          {row.name}
        </AppLink>
      </td>
      <td className="font-mono text-sm">{row.trigger ?? "—"}</td>
      <td className="font-mono text-sm">{row.runs}</td>
      <td
        className={cn("font-mono text-sm", row.failed > 0 && "text-destructive")}
        data-emphasis={row.failed > 0 ? "danger" : undefined}
      >
        {row.failed}
      </td>
      <td
        className={cn("font-mono text-sm", row.timed_out > 0 && "text-[var(--status-warning)]")}
        data-emphasis={row.timed_out > 0 ? "warning" : undefined}
      >
        {row.timed_out}
      </td>
      <td
        className={cn("font-mono text-sm", row.cancelled > 0 && "text-[var(--status-cancel)]")}
        data-emphasis={row.cancelled > 0 ? "cancel" : undefined}
      >
        {row.cancelled}
      </td>
      <td
        className={cn("font-mono text-sm", row.failed > 0 && "text-destructive")}
        data-emphasis={row.failed > 0 ? "danger" : undefined}
      >
        {errorRate}
      </td>
      <td className="font-mono text-sm">{avgDuration}</td>
      <td
        className={cn("font-mono text-sm", isOverdue && "text-[var(--status-warning)]")}
        data-emphasis={isOverdue ? "warning" : undefined}
      >
        {nextRunDisplay ?? "—"}
      </td>
    </tr>
  );
}

export function HandlerMobileRow({ row }: HandlerRowProps) {
  const { errorRate, avgDuration, nextRunDisplay, isScheduleStatus } = useHandlerRowData(row);

  return (
    <MobileCard
      href={handlerPath(row.app_key, row.kind, row.handlerId)}
      appKey={row.app_key}
      name={row.name}
      failing={row.failed > 0}
      data-testid={`${row.kind}-row-${row.id}`}
      metrics={
        <>
          <KindBadge kind={row.kind} />
          {row.trigger && <span>{row.trigger}</span>}
          <span>{row.runs} runs</span>
          {row.failed > 0 && (
            <span className="text-destructive" data-emphasis="danger">
              {row.failed} failed
            </span>
          )}
          {row.timed_out > 0 && (
            <span className="text-[var(--status-warning)]" data-emphasis="warning">
              {row.timed_out} timed out
            </span>
          )}
          {row.cancelled > 0 && (
            <span className="text-[var(--status-cancel)]" data-emphasis="cancel">
              {row.cancelled} cancelled
            </span>
          )}
          {row.runs > 0 && <span>{errorRate} err</span>}
          {row.avg_duration_ms > 0 && <span>avg {avgDuration}</span>}
        </>
      }
      footer={
        row.kind === "job" && nextRunDisplay !== null ? (
          <span className="text-muted-foreground" data-testid="handler-row-schedule-status">
            {isScheduleStatus ? nextRunDisplay : `next ${nextRunDisplay}`}
          </span>
        ) : undefined
      }
    />
  );
}
