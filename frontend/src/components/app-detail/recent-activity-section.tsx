import clsx from "clsx";
import { useMemo } from "preact/hooks";

import type { ActivityFeedEntryData } from "../../api/endpoints";
import { getAppActivity } from "../../api/endpoints";
import { useQueryInvalidator } from "../../hooks/use-query-invalidator";
import { useScopedQuery } from "../../hooks/use-scoped-query";
import { queryKeys } from "../../lib/query-keys";
import { useAppStore } from "../../state/store";
import { formatDurationOrDash, formatRelativeTime, lastDotSegment } from "../../utils/format";
import { executionStatusKind } from "../../utils/status";
import { StatusShape } from "../shared/status-shape";
import styles from "./overview-tab.module.css";

const ACTIVITY_FETCH_LIMIT = 20;
const ACTIVITY_ROW_LIMIT = 8;

interface ActivityGroup {
  key: string;
  handlerName: string;
  latestStatus: string;
  count: number;
  avgDurationMs: number | null;
  newestTs: number;
  oldestTs: number;
}

interface Accumulator {
  key: string;
  handlerName: string;
  latestStatus: string;
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
        <span class="ht-log-level-badge">
          <StatusShape kind={kind} size={8} />
        </span>
      </td>
      <td class={styles.activityName} title={group.handlerName}>
        {lastDotSegment(group.handlerName)}
        {isGrouped && <span class={styles.activityCount}> × {group.count}</span>}
      </td>
      <td class={styles.activityDuration}>{durationLabel}</td>
      <td class={styles.activityTime}>{timeLabel}</td>
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

  const executionCompleted = useAppStore((s) => s.executionCompleted);
  // Selecting tick (unused otherwise) subscribes this component to re-render on every tick,
  // which recomputes the relative-time labels rendered by ActivityGroupRow below.
  useAppStore((s) => s.tick);

  useQueryInvalidator(
    executionCompleted,
    (events) => events?.some((e: { app_key: string }) => e.app_key === appKey) ?? false,
    queryKeys.appActivity.prefix(appKey),
  );

  const groups = useMemo(() => summarizeActivityByHandler(activity ?? []).slice(0, ACTIVITY_ROW_LIMIT), [activity]);

  return (
    <section class={styles.section} data-testid="overview-activity-section">
      <h3 class="ht-section-label">recent activity</h3>
      {activityError ? (
        <p class={clsx(styles.emptyInline, "ht-text-danger")} data-testid="overview-activity-error">
          could not load activity
        </p>
      ) : !loading && (activity ?? []).length === 0 ? (
        <p class={styles.emptyInline} data-testid="overview-activity-empty">
          no recent activity
        </p>
      ) : (
        <table class={clsx("ht-table", styles.activityTable)}>
          <thead>
            <tr>
              <th class={styles.colDot} scope="col"></th>
              <th scope="col">Handler</th>
              <th class={styles.activityDuration} scope="col">
                Duration
              </th>
              <th class={styles.activityTime} scope="col">
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
      )}
    </section>
  );
}
