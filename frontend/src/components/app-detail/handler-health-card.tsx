import { useLocation } from "wouter";
import clsx from "clsx";
import type { UnifiedItem } from "./unified-handler-row";
import { StatusShape } from "../shared/status-shape";
import { Chip } from "../shared/chip";
import { Tooltip } from "../shared/tooltip";
import {
  pluralize,
  formatDuration,
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
      {/* Header: status shape + handler name */}
      <div class={styles.header}>
        <span aria-hidden="true">
          <StatusShape kind={item.statusKind} size={10} />
        </span>
        <span class={styles.name} title={item.name}>{item.name}</span>
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
        <Tooltip label={errorMessage}>
          <div class={styles.errorMessage}>{errorMessage}</div>
        </Tooltip>
      )}

      {/* Stats */}
      <div class={styles.stats}>
        <div class={styles.statRow}>
          <Tooltip label={`total ${callLabel}s`}>
            <span>{pluralize(runCount, callLabel)}</span>
          </Tooltip>
          {avgDuration !== null && avgDuration > 0 && (
            <Tooltip label="avg duration" class={styles.statRowEnd}>
              <span>{formatDuration(avgDuration)}</span>
            </Tooltip>
          )}
        </div>
        {(failed > 0 || lastActiveAt !== null) && (
          <div class={styles.statRow}>
            {failed > 0 && (
              <Tooltip label="error rate">
                <span>{formatRate(failed, total)}</span>
              </Tooltip>
            )}
            {lastActiveAt !== null && (
              <Tooltip label="last active" class={styles.statRowEnd}>
                <span>{formatRelativeTime(lastActiveAt)}</span>
              </Tooltip>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
