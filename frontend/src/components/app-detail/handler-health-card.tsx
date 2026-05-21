import clsx from "clsx";
import { useLocation } from "wouter";

import { useRelativeTime } from "../../hooks/use-relative-time";
import { STATUS_DOT_SIZE } from "../../utils/constants";
import { formatDuration, formatRate, pluralize } from "../../utils/format";
import { Chip } from "../shared/chip";
import { StatusShape } from "../shared/status-shape";
import { Tooltip } from "../shared/tooltip";
import styles from "./handler-health-card.module.css";
import {
  handlerPath,
  isFailing,
  itemErrorMessage,
  itemErrorType,
  itemKindChip,
  itemLastActiveAt,
  itemRunCount,
} from "./overview-tab-helpers";
import type { UnifiedItem } from "./unified-handler-row";

interface HandlerHealthCardProps {
  item: UnifiedItem;
  appKey: string;
  instanceQs: string;
}

export function HandlerHealthCard({ item, appKey, instanceQs }: HandlerHealthCardProps) {
  const [, navigate] = useLocation();
  const href = handlerPath(appKey, item, instanceQs);
  const failing = isFailing(item);
  const chipLabel = itemKindChip(item);
  const errorType = failing ? itemErrorType(item) : null;
  const errorMessage = failing ? itemErrorMessage(item) : null;
  const runCount = itemRunCount(item);
  const callLabel = item.kind === "listener" ? "call" : "run";
  const avgDuration = item.data.avg_duration_ms ?? null;
  const lastActiveAt = itemLastActiveAt(item);
  const lastActiveDisplay = useRelativeTime(lastActiveAt);
  const failed = item.data.failed;

  function handleKeyDown(e: KeyboardEvent) {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      navigate(href);
    }
  }

  return (
    <div
      class={clsx(styles.card, failing && styles.cardFailing)}
      data-testid={`overview-health-card-${item.kind}-${item.id}`}
      role="button"
      aria-label={`${item.name} handler details`}
      tabIndex={0}
      onClick={() => navigate(href)}
      onKeyDown={handleKeyDown}
    >
      <div class={styles.header}>
        <span aria-hidden="true">
          <StatusShape kind={item.statusKind} size={STATUS_DOT_SIZE} />
        </span>
        <span class={styles.name} title={item.name}>
          {item.name}
        </span>
      </div>

      <div class={styles.subtitle}>
        <Chip variant="muted" size="sm" aria-label={`kind: ${chipLabel}`}>
          {chipLabel}
        </Chip>
        {errorType && <span class={styles.errorType}>{errorType}</span>}
      </div>

      {errorMessage && (
        <Tooltip label={errorMessage}>
          <span class={styles.errorMessage}>{errorMessage}</span>
        </Tooltip>
      )}

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
                <span>{formatRate(failed, runCount)}</span>
              </Tooltip>
            )}
            {lastActiveAt !== null && (
              <Tooltip label="last active" class={styles.statRowEnd}>
                <span>{lastActiveDisplay}</span>
              </Tooltip>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
