import { useMemo, useState } from "preact/hooks";
import { Link, useLocation } from "wouter";
import clsx from "clsx";
import { EmptyState } from "../shared/empty-state";
import { LogTable } from "../shared/log-table";
import { StatusShape } from "../shared/status-shape";
import { buildItems } from "./handler-list";
import type { UnifiedItem } from "./unified-handler-row";
import { handlerKindLabel, executionStatusKind, INACTIVE_STATUSES } from "../../utils/status";
import { Chip } from "../shared/chip";
import { pluralize, formatDurationOrDash, formatRelativeTime, lastDotSegment } from "../../utils/format";
import { useSubscribe } from "../../hooks/use-subscribe";
import type { ListenerData, JobData, ActivityFeedEntryData } from "../../api/endpoints";
import { getAppActivity } from "../../api/endpoints";
import { useScopedApi } from "../../hooks/use-scoped-api";
import { useAppState } from "../../state/context";
import { useFilteredSignalRefetch, WS_DEBOUNCE_DELAY_MS, WS_DEBOUNCE_MAX_WAIT_MS } from "../../hooks/use-filtered-signal-refetch";
import styles from "./overview-tab.module.css";

const SPOTLIGHT_LIMIT = 3;

interface Props {
  listeners: ListenerData[];
  jobs: JobData[];
  appKey: string;
  instanceQs: string;
  resolvedInstanceIndex: number;
  appStatus?: string;
}

function handlerPath(appKey: string, item: UnifiedItem, instanceQs: string): string {
  const prefix = item.kind === "listener" ? "h" : "j";
  return `/apps/${appKey}/handlers/${prefix}-${item.id}${instanceQs}`;
}

function isFailing(item: UnifiedItem): boolean {
  return item.statusKind === "err";
}

function itemRunCount(item: UnifiedItem): number {
  return item.kind === "listener" ? item.data.total_invocations : item.data.total_executions;
}

function sortedByFailingFirst(items: UnifiedItem[]): UnifiedItem[] {
  return [...items].sort((a, b) => {
    const aFails = isFailing(a) ? 1 : 0;
    const bFails = isFailing(b) ? 1 : 0;
    if (bFails !== aFails) return bFails - aFails;
    return itemRunCount(b) - itemRunCount(a);
  });
}

function itemErrorType(item: UnifiedItem): string | null {
  return item.data.last_error_type ?? null;
}

function itemErrorMessage(item: UnifiedItem): string | null {
  return item.data.last_error_message ?? null;
}

function itemKindChip(item: UnifiedItem): string {
  if (item.kind === "listener") {
    return handlerKindLabel("listener", item.data.listener_kind, null);
  }
  return handlerKindLabel("job", null, item.data.trigger_type);
}

// ── Error Spotlight ───────────────────────────────────────────────────────────

interface SpotlightEntryProps {
  item: UnifiedItem;
  appKey: string;
  instanceQs: string;
}

function SpotlightEntry({ item, appKey, instanceQs }: SpotlightEntryProps) {
  const errorType = itemErrorType(item);
  const errorMessage = itemErrorMessage(item);
  const href = handlerPath(appKey, item, instanceQs);

  return (
    <div
      class={styles.spotlightEntry}
      data-testid={`overview-spotlight-entry-${item.kind}-${item.id}`}
    >
      <span aria-hidden="true">
        <StatusShape kind={item.statusKind} size={12} />
      </span>
      <div class={styles.spotlightBody}>
        <div class={styles.spotlightHeader}>
          <span class={styles.spotlightName}>{item.name}</span>
          {errorType && (
            <span class={styles.spotlightErrorType}>{errorType}</span>
          )}
        </div>
        {errorMessage && (
          <div class={styles.spotlightErrorMsg} title={errorMessage}>
            {errorMessage}
          </div>
        )}
      </div>
      <Link href={href} class={styles.spotlightLink}>
        view
      </Link>
    </div>
  );
}

interface ErrorSpotlightProps {
  failingItems: UnifiedItem[];
  appKey: string;
  instanceQs: string;
}

function ErrorSpotlight({ failingItems, appKey, instanceQs }: ErrorSpotlightProps) {
  const [expanded, setExpanded] = useState(false);

  const visibleItems = expanded ? failingItems : failingItems.slice(0, SPOTLIGHT_LIMIT);
  const hiddenCount = failingItems.length - SPOTLIGHT_LIMIT;

  return (
    <section
      class={clsx(styles.section, styles.spotlight)}
      data-testid="overview-error-spotlight"
    >
      <h3 class="ht-section-label">failing handlers</h3>
      {visibleItems.map((item) => (
        <SpotlightEntry
          key={`${item.kind}-${item.id}`}
          item={item}
          appKey={appKey}
          instanceQs={instanceQs}
        />
      ))}
      {!expanded && hiddenCount > 0 && (
        <button
          type="button"
          class={styles.spotlightShowMore}
          data-testid="overview-spotlight-show-more"
          onClick={() => setExpanded(true)}
        >
          show {hiddenCount} more
        </button>
      )}
    </section>
  );
}

// ── Handler Health Grid ───────────────────────────────────────────────────────

interface HealthGridRowProps {
  item: UnifiedItem;
  appKey: string;
  instanceQs: string;
}

function HealthGridRow({ item, appKey, instanceQs }: HealthGridRowProps) {
  const [, navigate] = useLocation();
  const href = handlerPath(appKey, item, instanceQs);
  const callLabel = item.kind === "listener" ? "call" : "run";
  const runCount = itemRunCount(item);
  const chipLabel = itemKindChip(item);

  return (
    <tr
      class={clsx(styles.healthRow, isFailing(item) && styles.healthRowFailing)}
      data-testid={`overview-health-row-${item.kind}-${item.id}`}
      tabIndex={0}
      role="row"
      onClick={() => navigate(href)}
      onKeyDown={(e: KeyboardEvent) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          navigate(href);
        }
      }}
    >
      <td>
        <StatusShape kind={item.statusKind} size={10} />
      </td>
      <td>
        <Chip variant="muted" size="sm" aria-label={`kind: ${chipLabel}`}>
          {chipLabel}
        </Chip>
      </td>
      <td class={styles.healthRowName}>
        <Link href={href} class={styles.healthRowLink} onClick={(e: MouseEvent) => e.stopPropagation()}>{item.name}</Link>
      </td>
      <td class={styles.healthRowCount}>
        {pluralize(runCount, callLabel)}
      </td>
      <td class={clsx(styles.healthRowError, "ht-text-danger ht-text-sm")}>
        {isFailing(item) && itemErrorType(item) ? itemErrorType(item) : null}
      </td>
    </tr>
  );
}

interface HandlerHealthGridProps {
  items: UnifiedItem[];
  appKey: string;
  instanceQs: string;
}

function HandlerHealthGrid({ items, appKey, instanceQs }: HandlerHealthGridProps) {
  const sorted = useMemo(() => sortedByFailingFirst(items), [items]);

  if (items.length === 0) {
    return (
      <section class={styles.section} data-testid="overview-health-grid">
        <h3 class="ht-section-label">handler health</h3>
        <EmptyState
          title="No handlers registered"
          body="This app has not registered any event handlers or scheduled jobs."
          data-testid="overview-health-empty"
        />
      </section>
    );
  }

  return (
    <section class={styles.section} data-testid="overview-health-grid">
      <h3 class="ht-section-label">handler health</h3>
      <table class={clsx("ht-table", styles.healthTable)}>
        <thead>
          <tr>
            <th class={styles.colDot} scope="col"></th>
            <th scope="col">Kind</th>
            <th scope="col">Handler</th>
            <th scope="col" style={{ textAlign: "right" }}>Runs</th>
            <th scope="col"></th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((item) => (
            <HealthGridRow
              key={`${item.kind}-${item.id}`}
              item={item}
              appKey={appKey}
              instanceQs={instanceQs}
            />
          ))}
        </tbody>
      </table>
    </section>
  );
}

// ── Recent Activity Section ───────────────────────────────────────────────────

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

function groupConsecutiveActivity(entries: ActivityFeedEntryData[]): ActivityGroup[] {
  const groups: ActivityGroup[] = [];
  for (const entry of entries) {
    const prev = groups[groups.length - 1];
    if (prev && prev.handlerName === entry.handler_name && prev.status === entry.status) {
      prev.count += 1;
      prev.lastTs = entry.timestamp;
      if (entry.duration_ms !== null && entry.duration_ms !== undefined) {
        if (prev.avgDurationMs !== null && prev.avgDurationMs !== undefined) {
          const prevTotal = prev.avgDurationMs * (prev.count - 1);
          prev.avgDurationMs = (prevTotal + entry.duration_ms) / prev.count;
        } else {
          prev.avgDurationMs = entry.duration_ms;
        }
      }
    } else {
      groups.push({
        key: entry.row_id,
        handlerName: entry.handler_name,
        status: entry.status,
        count: 1,
        avgDurationMs: entry.duration_ms ?? null,
        firstTs: entry.timestamp,
        lastTs: entry.timestamp,
      });
    }
  }
  return groups;
}

function ActivityGroupRow({ group }: { group: ActivityGroup }) {
  const kind = executionStatusKind(group.status);
  return (
    <tr data-testid="overview-activity-row">
      <td aria-label={`status: ${group.status}`}>
        <span class="ht-log-level-badge">
          <StatusShape kind={kind} size={8} />
        </span>
      </td>
      <td class={styles.activityName} title={group.handlerName}>
        {lastDotSegment(group.handlerName)}
        {group.count > 1 && (
          <span class={styles.activityCount}> × {group.count}</span>
        )}
      </td>
      <td class={styles.activityDuration}>
        {group.count > 1 && group.avgDurationMs !== null
          ? `avg ${formatDurationOrDash(group.avgDurationMs)}`
          : formatDurationOrDash(group.avgDurationMs)}
      </td>
      <td class={styles.activityTime}>
        {group.count > 1 && group.firstTs !== group.lastTs
          ? `${formatRelativeTime(group.firstTs)}–${formatRelativeTime(group.lastTs)}`
          : formatRelativeTime(group.firstTs)}
      </td>
    </tr>
  );
}

interface RecentActivitySectionProps {
  appKey: string;
  resolvedInstanceIndex: number;
}

function RecentActivitySection({ appKey, resolvedInstanceIndex }: RecentActivitySectionProps) {
  const { data: activity, loading, error: activityError, refetch } = useScopedApi(
    (since) => getAppActivity(appKey, resolvedInstanceIndex, ACTIVITY_LIMIT, since),
    { deps: [appKey, resolvedInstanceIndex] },
  );

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
              <th scope="col" style={{ textAlign: "right" }}>Duration</th>
              <th scope="col" style={{ textAlign: "right" }}>Time</th>
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

// ── Recent Logs Section ───────────────────────────────────────────────────────

function RecentLogsSection({ appKey, appStatus }: { appKey: string; appStatus?: string }) {
  const isInactive = appStatus !== undefined && INACTIVE_STATUSES.has(appStatus);
  return (
    <section class={styles.section} data-testid="overview-logs-section">
      <h3 class="ht-section-label">logs</h3>
      <div class={styles.logScroll}>
        <LogTable
          context="app"
          appKey={appKey}
          useLocalState
          {...(isInactive ? {
            emptyTitle: `this app is ${appStatus}`,
            emptyBody: "no logs have been recorded for this app.",
          } : {})}
        />
      </div>
    </section>
  );
}

// ── Overview Tab ──────────────────────────────────────────────────────────────

export function OverviewTab({ listeners, jobs, appKey, instanceQs, resolvedInstanceIndex, appStatus }: Props) {
  const { connection } = useAppState();
  const wsConnected = connection.value === "connected";
  const allItems = useMemo(() => buildItems(listeners, jobs), [listeners, jobs]);

  const failingItems = useMemo(() => allItems.filter(isFailing), [allItems]);

  return (
    <div class={clsx(styles.overviewTab, !wsConnected && styles.overviewTabStale)} data-testid="overview-tab">
      {failingItems.length > 0 && (
        <ErrorSpotlight
          failingItems={failingItems}
          appKey={appKey}
          instanceQs={instanceQs}
        />
      )}

      <HandlerHealthGrid
        items={allItems}
        appKey={appKey}
        instanceQs={instanceQs}
      />

      <RecentActivitySection appKey={appKey} resolvedInstanceIndex={resolvedInstanceIndex} />

      <RecentLogsSection appKey={appKey} appStatus={appStatus} />
    </div>
  );
}
