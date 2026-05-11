import { useMemo, useState } from "preact/hooks";
import { Link } from "wouter";
import { EmptyState } from "../shared/empty-state";
import { StatusShape } from "../shared/status-shape";
import { buildItems } from "./handler-list";
import type { UnifiedItem } from "./unified-handler-row";
import { handlerKindLabel, levelToKind, executionStatusKind } from "../../utils/status";
import { pluralize, formatDurationOrDash, lastDotSegment } from "../../utils/format";
import { useRelativeTime } from "../../hooks/use-relative-time";
import type { ListenerData, JobData, ActivityFeedEntryData, LogEntry } from "../../api/endpoints";
import { getAppActivity, getRecentLogs } from "../../api/endpoints";
import { useScopedApi } from "../../hooks/use-scoped-api";
import { useAppState } from "../../state/context";
import { useFilteredSignalRefetch, WS_DEBOUNCE_DELAY_MS, WS_DEBOUNCE_MAX_WAIT_MS } from "../../hooks/use-filtered-signal-refetch";

const SPOTLIGHT_LIMIT = 3;

interface Props {
  listeners: ListenerData[];
  jobs: JobData[];
  appKey: string;
  instanceQs: string;
  resolvedInstanceIndex: number;
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
      class="ht-overview-spotlight__entry"
      data-testid={`overview-spotlight-entry-${item.kind}-${item.id}`}
    >
      <span aria-hidden="true">
        <StatusShape kind={item.statusKind} size={12} />
      </span>
      <div class="ht-overview-spotlight__body">
        <div class="ht-overview-spotlight__header">
          <span class="ht-overview-spotlight__name">{item.name}</span>
          {errorType && (
            <span class="ht-overview-spotlight__error-type">{errorType}</span>
          )}
        </div>
        {errorMessage && (
          <div class="ht-overview-spotlight__error-msg" title={errorMessage}>
            {errorMessage}
          </div>
        )}
      </div>
      <Link href={href} class="ht-overview-spotlight__link">
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
      class="ht-overview-tab__section ht-overview-spotlight"
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
          class="ht-overview-spotlight__show-more"
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
  const href = handlerPath(appKey, item, instanceQs);
  const callLabel = item.kind === "listener" ? "call" : "run";
  const runCount = itemRunCount(item);
  const chipLabel = itemKindChip(item);

  return (
    <Link
      href={href}
      class="ht-overview-health-row"
      data-testid={`overview-health-row-${item.kind}-${item.id}`}
      aria-label={`${item.name} — ${chipLabel}`}
    >
      <span aria-hidden="true">
        <StatusShape kind={item.statusKind} size={10} />
      </span>
      <div class="ht-overview-health-row__meta">
        <span class="ht-chip ht-chip--muted ht-chip--sm" aria-label={`kind: ${chipLabel}`}>
          {chipLabel}
        </span>
        <span class="ht-overview-health-row__name">{item.name}</span>
      </div>
      <span class="ht-overview-health-row__count" title={`Total ${callLabel}s`}>
        {pluralize(runCount, callLabel)}
      </span>
      {isFailing(item) && itemErrorType(item) && (
        <span class="ht-overview-health-row__error ht-text-danger ht-text-sm">
          {itemErrorType(item)}
        </span>
      )}
    </Link>
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
      <section class="ht-overview-tab__section" data-testid="overview-health-grid">
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
    <section class="ht-overview-tab__section" data-testid="overview-health-grid">
      <h3 class="ht-section-label">handler health</h3>
      <div class="ht-overview-health-grid">
        {sorted.map((item) => (
          <HealthGridRow
            key={`${item.kind}-${item.id}`}
            item={item}
            appKey={appKey}
            instanceQs={instanceQs}
          />
        ))}
      </div>
    </section>
  );
}

// ── Recent Activity Section ───────────────────────────────────────────────────

const ACTIVITY_LIMIT = 20;
const LOGS_LIMIT = 10;

interface ActivityRowProps {
  entry: ActivityFeedEntryData;
}

function ActivityRow({ entry }: ActivityRowProps) {
  const kind = executionStatusKind(entry.status);
  const timeLabel = useRelativeTime(entry.timestamp);
  return (
    <tr data-testid="overview-activity-row">
      <td aria-label={`status: ${entry.status}`}>
        <span class="ht-log-level-badge">
          <StatusShape kind={kind} size={8} />
        </span>
      </td>
      <td class="ht-overview-activity__name" title={entry.handler_name}>{lastDotSegment(entry.handler_name)}</td>
      <td class="ht-overview-activity__duration">{formatDurationOrDash(entry.duration_ms)}</td>
      <td class="ht-overview-activity__time">{timeLabel}</td>
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

  const { invocationCompleted, executionCompleted } = useAppState();

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

  return (
    <section class="ht-overview-tab__section" data-testid="overview-activity-section">
      <h3 class="ht-section-label">recent activity</h3>
      {activityError.value ? (
        <p class="ht-overview-empty-inline ht-text-danger" data-testid="overview-activity-error">
          could not load activity
        </p>
      ) : !loading.value && entries.length === 0 ? (
        <p class="ht-overview-empty-inline" data-testid="overview-activity-empty">
          no recent activity
        </p>
      ) : (
        <table class="ht-table ht-overview-activity-table">
          <thead>
            <tr>
              <th class="ht-overview-activity__status-header"></th>
              <th class="ht-overview-activity__name-header">Handler</th>
              <th class="ht-overview-activity__duration-header">Duration</th>
              <th class="ht-overview-activity__time-header">Time</th>
            </tr>
          </thead>
          <tbody aria-live="polite" aria-atomic="false">
            {entries.map((entry) => (
              <ActivityRow key={entry.row_id} entry={entry} />
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

// ── Recent Logs Section ───────────────────────────────────────────────────────

interface LogRowProps {
  entry: LogEntry;
}

function LogRow({ entry }: LogRowProps) {
  const kind = levelToKind(entry.level);
  const timeLabel = useRelativeTime(entry.timestamp);
  return (
    <tr data-level={entry.level} data-testid="overview-log-row">
      <td aria-label={`level: ${entry.level}`}>
        <span class="ht-log-level-badge">
          <StatusShape kind={kind} size={8} />
          <span class="ht-log-level-badge__text">{entry.level}</span>
        </span>
      </td>
      <td class="ht-overview-log__time">{timeLabel}</td>
      <td class="ht-overview-log__message" title={entry.message}>{entry.message}</td>
    </tr>
  );
}

interface RecentLogsSectionProps {
  appKey: string;
}

function RecentLogsSection({ appKey }: RecentLogsSectionProps) {
  const { data: logs, loading, error: logsError, refetch } = useScopedApi(
    (since) => getRecentLogs({ app_key: appKey, limit: LOGS_LIMIT, since }),
    { deps: [appKey] },
  );

  const { executionCompleted } = useAppState();

  useFilteredSignalRefetch(
    executionCompleted,
    (events) => events?.some((e) => e.app_key === appKey) ?? false,
    () => void refetch(),
    WS_DEBOUNCE_DELAY_MS,
    WS_DEBOUNCE_MAX_WAIT_MS,
  );

  const entries = logs.value ?? [];

  return (
    <section class="ht-overview-tab__section" data-testid="overview-logs-section">
      <h3 class="ht-section-label">recent logs</h3>
      {logsError.value ? (
        <p class="ht-overview-empty-inline ht-text-danger" data-testid="overview-logs-error">
          could not load logs
        </p>
      ) : !loading.value && entries.length === 0 ? (
        <p class="ht-overview-empty-inline" data-testid="overview-logs-empty">
          no recent logs
        </p>
      ) : (
        <table class="ht-table ht-overview-log-table">
          <thead>
            <tr>
              <th class="ht-overview-log__level-header">Level</th>
              <th class="ht-overview-log__time-header">Time</th>
              <th class="ht-overview-log__message-header">Message</th>
            </tr>
          </thead>
          <tbody>
            {entries.map((entry) => (
              <LogRow key={entry.seq} entry={entry} />
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

// ── Overview Tab ──────────────────────────────────────────────────────────────

export function OverviewTab({ listeners, jobs, appKey, instanceQs, resolvedInstanceIndex }: Props) {
  const { connection } = useAppState();
  const wsConnected = connection.value === "connected";
  const allItems = useMemo(() => buildItems(listeners, jobs), [listeners, jobs]);

  const failingItems = useMemo(() => allItems.filter(isFailing), [allItems]);

  return (
    <div class={`ht-overview-tab${!wsConnected ? " ht-overview-tab--stale" : ""}`} data-testid="overview-tab">
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

      <RecentLogsSection appKey={appKey} />
    </div>
  );
}
