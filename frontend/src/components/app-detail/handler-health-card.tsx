import { useLocation, Link } from "wouter";
import clsx from "clsx";
import type { UnifiedItem } from "./unified-handler-row";
import { StatusShape } from "../shared/status-shape";
import { Chip } from "../shared/chip";
import {
  pluralize,
  formatDurationOrDash,
  formatRelativeTime,
  formatRate,
} from "../../utils/format";
import {
  handlerPath,
  isFailing,
  itemRunCount,
  itemErrorType,
  itemErrorMessage,
  itemKindChip,
} from "./overview-tab";
import styles from "./handler-health-card.module.css";

interface HandlerHealthCardProps {
  item: UnifiedItem;
  appKey: string;
  instanceQs: string;
}

function itemLastActiveAt(item: UnifiedItem): number | null {
  return item.kind === "listener"
    ? (item.data.last_invoked_at ?? null)
    : (item.data.last_executed_at ?? null);
}

export function HandlerHealthCard({ item, appKey, instanceQs }: HandlerHealthCardProps) {
  const [, navigate] = useLocation();
  const href = handlerPath(appKey, item, instanceQs);
  const failing = isFailing(item);
  const chipLabel = itemKindChip(item);
  const errorType = failing ? (itemErrorType(item) ?? (item.data.timed_out > 0 ? "timed out" : null)) : null;
  const errorMessage = failing ? itemErrorMessage(item) : null;
  const runCount = itemRunCount(item);
  const callLabel = item.kind === "listener" ? "call" : "run";
  const avgDuration = item.data.avg_duration_ms ?? null;
  const lastActiveAt = itemLastActiveAt(item);
  const failed = item.data.failed;
  const total = runCount;

  return (
    <div
      class={clsx(styles.card, failing && styles.cardFailing)}
      data-testid={`overview-health-card-${item.kind}-${item.id}`}
      role="article"
      tabIndex={0}
      onClick={() => navigate(href)}
      onKeyDown={(e: KeyboardEvent) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          navigate(href);
        }
      }}
    >
      {/* Header: status shape + handler name link */}
      <div class={styles.header}>
        <span aria-hidden="true">
          <StatusShape kind={item.statusKind} size={10} />
        </span>
        <Link
          href={href}
          class={styles.name}
          title={item.name}
          onClick={(e: MouseEvent) => e.stopPropagation()}
        >
          {item.name}
        </Link>
      </div>

      {/* Subtitle: kind chip + error type (if failing) */}
      <div class={styles.subtitle}>
        <Chip variant="muted" size="sm" aria-label={`kind: ${chipLabel}`}>
          {chipLabel}
        </Chip>
        {errorType && (
          <span class={styles.errorType}>{errorType}</span>
        )}
      </div>

      {/* Error message (if failing and present) */}
      {errorMessage && (
        <div class={styles.errorMessage} title={errorMessage}>
          {errorMessage}
        </div>
      )}

      {/* Stats */}
      <div class={styles.stats}>
        <div class={styles.statRow}>
          <span>{pluralize(runCount, callLabel)}</span>
          <span class={styles.statRowEnd}>{formatDurationOrDash(avgDuration)}</span>
        </div>
        <div class={styles.statRow}>
          {failed > 0 && (
            <span>{formatRate(failed, total)}</span>
          )}
          <span class={styles.statRowEnd}>
            {lastActiveAt !== null ? formatRelativeTime(lastActiveAt) : "—"}
          </span>
        </div>
      </div>
    </div>
  );
}
