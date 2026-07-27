import clsx from "clsx";
import { useLocation } from "wouter";

import { useRelativeTime } from "../../hooks/use-relative-time";
import { STATUS_DOT_SIZE } from "../../utils/constants";
import { formatDuration, formatRate, pluralize } from "../../utils/format";
import { onActivateKeyDown } from "../../utils/keyboard";
import { Chip } from "../shared/chip";
import { StatusShape } from "../shared/status-shape";
import { Tooltip } from "../shared/tooltip";
import styles from "./handler-health-card.module.css";
import {
  handlerHref,
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
  tabIndex: 0 | -1;
}

export function HandlerHealthCard({ item, appKey, instanceQs, tabIndex }: HandlerHealthCardProps) {
  const [, navigate] = useLocation();
  const href = handlerHref(appKey, item, instanceQs);
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

  const navigateToHandler = () => navigate(href);

  const idle = item.statusKind === "mute";

  return (
    <div
      className={clsx(styles.card, failing && styles.cardFailing, idle && styles.cardIdle)}
      data-testid={`overview-health-card-${item.kind}-${item.id}`}
      role="button"
      aria-label={`${item.name} handler details`}
      tabIndex={tabIndex}
      data-roving-item
      onClick={navigateToHandler}
      onKeyDown={onActivateKeyDown(navigateToHandler)}
    >
      <div className={styles.header}>
        <span aria-hidden="true">
          <StatusShape kind={item.statusKind} size={STATUS_DOT_SIZE} />
        </span>
        <span className={styles.name} title={item.name}>
          {item.name}
        </span>
      </div>

      <div className={styles.subtitle}>
        <Chip variant={item.kind} size="sm" aria-label={`kind: ${chipLabel}`}>
          {chipLabel}
        </Chip>
        {errorType && <span className={styles.errorType}>{errorType}</span>}
      </div>

      {errorMessage && (
        <Tooltip label={errorMessage}>
          <span className={styles.errorMessage}>{errorMessage}</span>
        </Tooltip>
      )}

      <div className={styles.stats}>
        <div className={styles.statRow}>
          <Tooltip label={`total ${callLabel}s`}>
            <span>{pluralize(runCount, callLabel)}</span>
          </Tooltip>
          {avgDuration !== null && avgDuration > 0 && (
            <Tooltip label="avg duration" className={styles.statRowEnd}>
              <span>{formatDuration(avgDuration)}</span>
            </Tooltip>
          )}
        </div>
        {(failed > 0 || lastActiveAt !== null) && (
          <div className={styles.statRow}>
            {failed > 0 && (
              <Tooltip label="error rate">
                <span>{formatRate(failed, runCount)}</span>
              </Tooltip>
            )}
            {lastActiveAt !== null && (
              <Tooltip label="last active" className={styles.statRowEnd}>
                <span>{lastActiveDisplay}</span>
              </Tooltip>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
