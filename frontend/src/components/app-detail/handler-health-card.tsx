import type { ReactNode } from "react";
import { useLocation } from "wouter";

import { Badge } from "@/components/ui/badge";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

import { useRelativeTime } from "../../hooks/use-relative-time";
import { STATUS_DOT_SIZE } from "../../utils/constants";
import { formatDuration, formatRate, pluralize } from "../../utils/format";
import { onActivateKeyDown } from "../../utils/keyboard";
import { StatusShape } from "../shared/status-shape";
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

function StatTooltip({ label, className, children }: { label: string; className?: string; children: ReactNode }) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span className={className} tabIndex={0}>
          {children}
        </span>
      </TooltipTrigger>
      <TooltipContent>{label}</TooltipContent>
    </Tooltip>
  );
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
    <TooltipProvider>
      <div
        className={cn(styles.card, failing && styles.cardFailing, idle && styles.cardIdle)}
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
          <Badge variant={item.kind} size="sm" aria-label={`kind: ${chipLabel}`}>
            {chipLabel}
          </Badge>
          {errorType && <span className={styles.errorType}>{errorType}</span>}
        </div>

        {errorMessage && (
          <StatTooltip label={errorMessage}>
            <span className={styles.errorMessage}>{errorMessage}</span>
          </StatTooltip>
        )}

        <div className={styles.stats}>
          <div className={styles.statRow}>
            <StatTooltip label={`total ${callLabel}s`}>
              <span>{pluralize(runCount, callLabel)}</span>
            </StatTooltip>
            {avgDuration !== null && avgDuration > 0 && (
              <StatTooltip label="avg duration" className={styles.statRowEnd}>
                <span>{formatDuration(avgDuration)}</span>
              </StatTooltip>
            )}
          </div>
          {(failed > 0 || lastActiveAt !== null) && (
            <div className={styles.statRow}>
              {failed > 0 && (
                <StatTooltip label="error rate">
                  <span>{formatRate(failed, runCount)}</span>
                </StatTooltip>
              )}
              {lastActiveAt !== null && (
                <StatTooltip label="last active" className={styles.statRowEnd}>
                  <span>{lastActiveDisplay}</span>
                </StatTooltip>
              )}
            </div>
          )}
        </div>
      </div>
    </TooltipProvider>
  );
}
