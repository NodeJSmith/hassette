import clsx from "clsx";
import { useMemo } from "preact/hooks";

import type { ActivityFeedEntryData } from "../../api/endpoints";
import { getAppActivity } from "../../api/endpoints";
import {
  useFilteredSignalRefetch,
  WS_DEBOUNCE_DELAY_MS,
  WS_DEBOUNCE_MAX_WAIT_MS,
} from "../../hooks/use-filtered-signal-refetch";
import { useScopedApi } from "../../hooks/use-scoped-api";
import { useSubscribe } from "../../hooks/use-subscribe";
import { useAppState } from "../../state/context";
import { formatDurationOrDash, formatRelativeTime, lastDotSegment } from "../../utils/format";
import { executionStatusKind } from "../../utils/status";
import { StatusShape } from "../shared/status-shape";
import styles from "./overview-tab.module.css";

const ACTIVITY_LIMIT = 20;

interface ActivityGroup {
  key: string;
  handlerName: string;
  status: string;
  count: number;
  avgDurationMs: number | null;
  firstTs: number;
  lastTs: number;
}

interface Accumulator {
  key: string;
  handlerName: string;
  status: string;
  count: number;
  durationSum: number;
  durationCount: number;
  firstTs: number;
  lastTs: number;
}

function groupConsecutiveActivity(entries: ActivityFeedEntryData[]): ActivityGroup[] {
  const accumulators: Accumulator[] = [];
  for (const entry of entries) {
    const prev = accumulators[accumulators.length - 1];
    if (prev && prev.handlerName === entry.handler_name && prev.status === entry.status) {
      const dur = entry.duration_ms ?? null;
      accumulators[accumulators.length - 1] = {
        ...prev,
        count: prev.count + 1,
        lastTs: entry.timestamp,
        durationSum: prev.durationSum + (dur !== null ? dur : 0),
        durationCount: prev.durationCount + (dur !== null ? 1 : 0),
      };
    } else {
      const dur = entry.duration_ms ?? null;
      accumulators.push({
        key: entry.row_id,
        handlerName: entry.handler_name,
        status: entry.status,
        count: 1,
        durationSum: dur !== null ? dur : 0,
        durationCount: dur !== null ? 1 : 0,
        firstTs: entry.timestamp,
        lastTs: entry.timestamp,
      });
    }
  }
  return accumulators.map((acc) => ({
    key: acc.key,
    handlerName: acc.handlerName,
    status: acc.status,
    count: acc.count,
    avgDurationMs: acc.durationCount > 0 ? acc.durationSum / acc.durationCount : null,
    firstTs: acc.firstTs,
    lastTs: acc.lastTs,
  }));
}

function ActivityGroupRow({ group }: { group: ActivityGroup }) {
  const kind = executionStatusKind(group.status);
  const isGrouped = group.count > 1;
  const durationLabel =
    isGrouped && group.avgDurationMs !== null
      ? `avg ${formatDurationOrDash(group.avgDurationMs)}`
      : formatDurationOrDash(group.avgDurationMs);
  const timeLabel =
    isGrouped && group.firstTs !== group.lastTs
      ? `${formatRelativeTime(group.firstTs)}–${formatRelativeTime(group.lastTs)}`
      : formatRelativeTime(group.firstTs);

  return (
    <tr data-testid="overview-activity-row">
      <td aria-label={`status: ${group.status}`}>
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
    loading,
    error: activityError,
    refetch,
  } = useScopedApi((since) => getAppActivity(appKey, resolvedInstanceIndex, ACTIVITY_LIMIT, since), {
    deps: [appKey, resolvedInstanceIndex],
  });

  const { invocationCompleted, executionCompleted, tick } = useAppState();
  useSubscribe(tick);

  useFilteredSignalRefetch(
    invocationCompleted,
    (events) => events?.some((e) => e.app_key === appKey) ?? false,
    () => void refetch(),
    WS_DEBOUNCE_DELAY_MS,
    WS_DEBOUNCE_MAX_WAIT_MS,
  );

  useFilteredSignalRefetch(
    executionCompleted,
    (events) => events?.some((e) => e.app_key === appKey) ?? false,
    () => void refetch(),
    WS_DEBOUNCE_DELAY_MS,
    WS_DEBOUNCE_MAX_WAIT_MS,
  );

  const entries = activity.value ?? [];
  const groups = useMemo(() => groupConsecutiveActivity(entries), [entries]);

  return (
    <section class={styles.section} data-testid="overview-activity-section">
      <h3 class="ht-section-label">recent activity</h3>
      {activityError.value ? (
        <p class={clsx(styles.emptyInline, "ht-text-danger")} data-testid="overview-activity-error">
          could not load activity
        </p>
      ) : !loading.value && entries.length === 0 ? (
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
