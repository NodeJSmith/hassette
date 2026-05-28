import clsx from "clsx";

import { AppLink } from "../components/shared/app-link";
import { Chip } from "../components/shared/chip";
import { useRelativeTime } from "../hooks/use-relative-time";
import { formatDurationOrDash, formatRate, MS_PER_SECOND } from "../utils/format";
import type { UnifiedRow } from "../utils/handler-rows";
import styles from "./handlers.module.css";

// Coarse kind labels for the table view — overview-tab-helpers uses handlerKindLabel() for richer per-listener kinds
const KIND_LABELS: Record<"listener" | "job", string> = {
  listener: "event",
  job: "job",
};

function KindBadge({ kind }: { kind: "listener" | "job" }) {
  return (
    <Chip variant="muted" size="sm">
      {KIND_LABELS[kind]}
    </Chip>
  );
}

interface MobileCardProps {
  href: string;
  appKey: string;
  name: string;
  failing?: boolean;
  "data-testid"?: string;
  metrics: preact.ComponentChildren;
  footer?: preact.ComponentChildren;
}

function MobileCard({ href, appKey, name, failing, metrics, footer, ...rest }: MobileCardProps) {
  return (
    <a
      href={href}
      class={clsx(styles.mobileCard, failing && styles.mobileCardFailing)}
      data-testid={rest["data-testid"]}
    >
      <div class={styles.mobileCardHeader}>
        <span class="ht-text-mono ht-text-sm">{appKey}</span>
        <span class="ht-text-mono ht-text-sm ht-text-semibold">{name}</span>
      </div>
      <div class={styles.mobileCardMetrics}>{metrics}</div>
      {footer && <div class={styles.mobileCardFooter}>{footer}</div>}
    </a>
  );
}

function useHandlerRowData(row: UnifiedRow) {
  const nextRunRelative = useRelativeTime(row.next_run_ts);
  const errorRate = formatRate(row.failed, row.runs);
  const avgDur = formatDurationOrDash(row.avg_duration_ms);
  const now = Date.now() / MS_PER_SECOND;
  const isOverdue = row.next_run_ts !== null && row.next_run_ts < now;
  const nextRunDisplay = row.next_run_ts !== null ? (isOverdue ? "overdue" : nextRunRelative) : null;
  return { errorRate, avgDur, isOverdue, nextRunDisplay };
}

interface HandlerRowProps {
  row: UnifiedRow;
}

export function HandlerTableRow({ row }: HandlerRowProps) {
  const { errorRate, avgDur, isOverdue, nextRunDisplay } = useHandlerRowData(row);

  return (
    <tr class={clsx(styles.row, row.failed > 0 && styles.rowFailing)} data-testid={`${row.kind}-row-${row.id}`}>
      <td>
        <KindBadge kind={row.kind} />
      </td>
      <td class="ht-text-mono ht-text-sm">
        <AppLink appKey={row.app_key} />
      </td>
      <td class="ht-text-mono ht-text-sm" title={row.handler_method}>
        <AppLink appKey={row.app_key} handlerId={row.id}>
          {row.name}
        </AppLink>
      </td>
      <td class="ht-text-mono ht-text-sm">{row.trigger ?? "—"}</td>
      <td class="ht-text-mono ht-text-sm">{row.runs}</td>
      <td class={clsx("ht-text-mono ht-text-sm", row.failed > 0 && "ht-text-danger")}>{row.failed}</td>
      <td class={clsx("ht-text-mono ht-text-sm", row.timed_out > 0 && "ht-text-warning")}>{row.timed_out}</td>
      <td class={clsx("ht-text-mono ht-text-sm", row.failed > 0 && "ht-text-danger")}>{errorRate}</td>
      <td class="ht-text-mono ht-text-sm">{avgDur}</td>
      <td class={clsx("ht-text-mono ht-text-sm", isOverdue && "ht-text-warning")}>{nextRunDisplay ?? "—"}</td>
    </tr>
  );
}

export function HandlerMobileRow({ row }: HandlerRowProps) {
  const { errorRate, avgDur, nextRunDisplay } = useHandlerRowData(row);

  return (
    <MobileCard
      href={`/apps/${row.app_key}/handlers/${row.id}`}
      appKey={row.app_key}
      name={row.name}
      failing={row.failed > 0}
      data-testid={`${row.kind}-row-${row.id}`}
      metrics={
        <>
          <KindBadge kind={row.kind} />
          {row.trigger && <span>{row.trigger}</span>}
          <span>{row.runs} runs</span>
          {row.failed > 0 && <span class="ht-text-danger">{row.failed} failed</span>}
          {row.timed_out > 0 && <span class="ht-text-warning">{row.timed_out} timed out</span>}
          {row.runs > 0 && <span>{errorRate} err</span>}
          {row.avg_duration_ms > 0 && <span>avg {avgDur}</span>}
        </>
      }
      footer={
        row.kind === "job" && nextRunDisplay !== null ? (
          <span class="ht-text-muted">next {nextRunDisplay}</span>
        ) : undefined
      }
    />
  );
}
