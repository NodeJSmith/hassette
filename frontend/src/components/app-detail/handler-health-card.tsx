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

const STAT_ROW_CLASS = "flex gap-3 font-mono text-[length:var(--text-mono-sm)] text-muted-foreground";

interface StatTooltipProps {
  label: string;
  className?: string;
  /**
   * Mirrors the owning card's roving tabindex so a non-active card contributes no tab stops
   * of its own, while the active card keeps its tooltips keyboard-reachable.
   */
  tabIndex: 0 | -1;
  children: ReactNode;
}

function StatTooltip({ label, className, tabIndex, children }: StatTooltipProps) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span className={className} tabIndex={tabIndex}>
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
  const failedCount = item.data.failed;

  const navigateToHandler = () => navigate(href);

  const idle = item.statusKind === "mute";

  return (
    <TooltipProvider>
      <div
        className={cn(
          "flex cursor-pointer flex-col gap-2 rounded-md border border-border bg-card p-3",
          "transition-[background-color,box-shadow,opacity] [box-shadow:var(--shadow-2)] hover:bg-muted hover:[box-shadow:var(--shadow-3)]",
          "focus-visible:outline-solid focus-visible:outline-2 focus-visible:outline-primary focus-visible:outline-offset-0",
          failing &&
            "border-t-[var(--border-width-medium)] border-t-destructive hover:bg-[color-mix(in_srgb,var(--destructive-bg)_40%,var(--muted))]",
          idle && "opacity-60 hover:opacity-100 focus-visible:opacity-100",
        )}
        data-testid={`overview-health-card-${item.kind}-${item.id}`}
        role="button"
        aria-label={`${item.name} handler details`}
        tabIndex={tabIndex}
        data-roving-item
        onClick={navigateToHandler}
        onKeyDown={onActivateKeyDown(navigateToHandler)}
      >
        <div className="flex min-w-0 items-center gap-2">
          <span aria-hidden="true">
            <StatusShape kind={item.statusKind} size={STATUS_DOT_SIZE} />
          </span>
          <span
            className="min-w-0 flex-1 truncate font-mono text-[length:var(--text-mono-sm)] text-foreground"
            title={item.name}
          >
            {item.name}
          </span>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <Badge variant={item.kind} size="sm" aria-label={`kind: ${chipLabel}`}>
            {chipLabel}
          </Badge>
          {errorType && <span className="whitespace-nowrap text-sm text-destructive">{errorType}</span>}
        </div>

        {errorMessage && (
          <StatTooltip label={errorMessage} tabIndex={tabIndex}>
            <span className="block max-w-full truncate text-sm text-muted-foreground">{errorMessage}</span>
          </StatTooltip>
        )}

        <div className="flex flex-col gap-1">
          <div className={STAT_ROW_CLASS}>
            <StatTooltip label={`total ${callLabel}s`} tabIndex={tabIndex}>
              <span>{pluralize(runCount, callLabel)}</span>
            </StatTooltip>
            {avgDuration !== null && avgDuration > 0 && (
              <StatTooltip label="avg duration" className="ml-auto" tabIndex={tabIndex}>
                <span>{formatDuration(avgDuration)}</span>
              </StatTooltip>
            )}
          </div>
          {(failedCount > 0 || lastActiveAt !== null) && (
            <div className={STAT_ROW_CLASS}>
              {failedCount > 0 && (
                <StatTooltip label="error rate" tabIndex={tabIndex}>
                  <span>{formatRate(failedCount, runCount)}</span>
                </StatTooltip>
              )}
              {lastActiveAt !== null && (
                <StatTooltip label="last active" className="ml-auto" tabIndex={tabIndex}>
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
