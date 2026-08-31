import { useMemo } from "react";

import { cn } from "@/lib/utils";

import type { ActivityFeedEntryData } from "../../api/endpoints";
import { getAppActivity } from "../../api/endpoints";
import type { components } from "../../api/generated-types";
import { useQueryInvalidator } from "../../hooks/use-query-invalidator";
import { isExecutionDefined, useAppExecution } from "../../hooks/use-scoped-execution";
import { useScopedQuery } from "../../hooks/use-scoped-query";
import { queryKeys } from "../../lib/query-keys";
import { useAppStore } from "../../state/store";
import { STATUS_DOT_SIZE } from "../../utils/constants";
import { formatDurationOrDash, formatRelativeTime, lastDotSegment } from "../../utils/format";
import { executionStatusKind } from "../../utils/status";
import { StatusShape } from "../shared/status-shape";
import { OVERVIEW_SECTION_CLASS, SECTION_LABEL_CLASS } from "./overview-section";

const ACTIVITY_FETCH_LIMIT = 20;
const ACTIVITY_ROW_LIMIT = 8;
const DATA_TABLE_CLASS =
  "w-full border-collapse bg-card [&_thead_tr]:bg-muted [&_th]:border-b [&_th]:border-border [&_th]:px-3 [&_th]:py-2 [&_th]:text-left [&_th]:font-mono [&_th]:text-xs [&_th]:font-medium [&_th]:uppercase [&_th]:tracking-[var(--text-label-tracking)] [&_th]:text-muted-foreground [&_th]:whitespace-nowrap [&_td]:border-b [&_td]:border-border [&_td]:px-3 [&_td]:py-2 [&_td]:align-top [&_td]:text-[length:var(--text-small)] [&_tbody_tr:last-child_td]:border-b-0 [&_tbody_tr:hover]:bg-muted";

type ExecutionStatus = components["schemas"]["ExecutionStatus"];

interface ActivityGroup {
  key: string;
  handlerName: string;
  latestStatus: ExecutionStatus;
  count: number;
  avgDurationMs: number | null;
  newestTs: number;
  oldestTs: number;
}

interface Accumulator {
  key: string;
  handlerName: string;
  latestStatus: ExecutionStatus;
  count: number;
  durationSum: number;
  durationCount: number;
  newestTs: number;
  oldestTs: number;
}

function summarizeActivityByHandler(entries: ActivityFeedEntryData[]): ActivityGroup[] {
  const accumulators = new Map<string, Accumulator>();
  const newestFirst = [...entries].sort((a, b) => b.timestamp - a.timestamp);
  for (const entry of newestFirst) {
    const key = `${entry.kind}:${entry.handler_id}`;
    const prev = accumulators.get(key);
    if (prev) {
      const dur = entry.duration_ms ?? null;
      accumulators.set(key, {
        ...prev,
        count: prev.count + 1,
        oldestTs: Math.min(prev.oldestTs, entry.timestamp),
        durationSum: prev.durationSum + (dur !== null ? dur : 0),
        durationCount: prev.durationCount + (dur !== null ? 1 : 0),
      });
    } else {
      const dur = entry.duration_ms ?? null;
      accumulators.set(key, {
        key,
        handlerName: entry.handler_name,
        latestStatus: entry.status,
        count: 1,
        durationSum: dur !== null ? dur : 0,
        durationCount: dur !== null ? 1 : 0,
        newestTs: entry.timestamp,
        oldestTs: entry.timestamp,
      });
    }
  }
  return Array.from(accumulators.values()).map((acc) => ({
    key: acc.key,
    handlerName: acc.handlerName,
    latestStatus: acc.latestStatus,
    count: acc.count,
    avgDurationMs: acc.durationCount > 0 ? acc.durationSum / acc.durationCount : null,
    newestTs: acc.newestTs,
    oldestTs: acc.oldestTs,
  }));
}

function ActivityGroupRow({ group }: { group: ActivityGroup }) {
  const kind = executionStatusKind(group.latestStatus);
  const isGrouped = group.count > 1;
  const durationLabel =
    isGrouped && group.avgDurationMs !== null
      ? `avg ${formatDurationOrDash(group.avgDurationMs)}`
      : formatDurationOrDash(group.avgDurationMs);
  const newestTimeLabel = formatRelativeTime(group.newestTs);
  const oldestTimeLabel = formatRelativeTime(group.oldestTs);
  const timeLabel =
    isGrouped && newestTimeLabel !== oldestTimeLabel ? `${newestTimeLabel}–${oldestTimeLabel}` : newestTimeLabel;

  return (
    <tr data-testid="overview-activity-row">
      <td aria-label={`latest status: ${group.latestStatus}`}>
        <span className="inline-flex items-center gap-1 whitespace-nowrap font-mono text-[length:var(--text-mono-sm)] leading-none">
          <StatusShape kind={kind} size={STATUS_DOT_SIZE} />
        </span>
      </td>
      <td className="text-foreground" title={group.handlerName}>
        {lastDotSegment(group.handlerName)}
        {isGrouped && <span className="font-normal text-muted-foreground"> × {group.count}</span>}
      </td>
      <td className="whitespace-nowrap text-right text-muted-foreground">{durationLabel}</td>
      <td className="whitespace-nowrap text-right text-muted-foreground">{timeLabel}</td>
    </tr>
  );
}

export function RecentActivitySection({
  appKey,
  resolvedInstanceIndex,
}: {
  appKey: string;
  resolvedInstanceIndex: number;
}) {
  const {
    data: activity,
    isPending: loading,
    error: activityError,
  } = useScopedQuery(queryKeys.appActivity.base(appKey, resolvedInstanceIndex), (since, signal) =>
    getAppActivity(appKey, resolvedInstanceIndex, ACTIVITY_FETCH_LIMIT, since, signal),
  );

  const execution = useAppExecution(appKey);
  // Selecting tick (unused otherwise) subscribes this component to re-render on every tick,
  // which recomputes the relative-time labels rendered by ActivityGroupRow below.
  useAppStore((s) => s.tick);

  useQueryInvalidator(execution, isExecutionDefined, queryKeys.appActivity.prefix(appKey));

  const groups = useMemo(() => summarizeActivityByHandler(activity ?? []).slice(0, ACTIVITY_ROW_LIMIT), [activity]);

  return (
    <section className={OVERVIEW_SECTION_CLASS} data-testid="overview-activity-section">
      <h3 className={SECTION_LABEL_CLASS}>recent activity</h3>
      {activityError ? (
        <p className="mt-2 p-0 text-sm text-destructive" data-testid="overview-activity-error">
          could not load activity
        </p>
      ) : !loading && (activity ?? []).length === 0 ? (
        <p className="mt-2 p-0 text-sm text-muted-foreground" data-testid="overview-activity-empty">
          no recent activity
        </p>
      ) : (
        // The nowrap duration/time columns can exceed the content width on
        // mobile — scroll the table locally instead of the whole main column.
        <div className="overflow-x-auto" data-testid="overview-activity-scroll">
          <table
            className={cn(
              DATA_TABLE_CLASS,
              "[&_td]:align-middle [&_td]:font-mono [&_td]:text-[length:var(--text-mono-sm)] [&_td]:text-foreground-secondary",
            )}
          >
            <thead>
              <tr>
                <th className="w-7" scope="col"></th>
                <th scope="col">Handler</th>
                <th className="whitespace-nowrap text-right text-muted-foreground" scope="col">
                  Duration
                </th>
                <th className="whitespace-nowrap text-right text-muted-foreground" scope="col">
                  Time
                </th>
              </tr>
            </thead>
            <tbody aria-live="polite" aria-atomic="false">
              {groups.map((group) => (
                <ActivityGroupRow key={group.key} group={group} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
