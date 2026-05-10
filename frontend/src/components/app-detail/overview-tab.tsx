import { useState } from "preact/hooks";
import { Link } from "wouter";
import { EmptyState } from "../shared/empty-state";
import { StatusShape } from "../shared/status-shape";
import { buildItems } from "./handler-list";
import type { UnifiedItem } from "./unified-handler-row";
import { handlerKindLabel, levelToKind, executionStatusKind } from "../../utils/status";
import { pluralize, formatDurationOrDash, formatRelativeTime } from "../../utils/format";
import type { ListenerData, JobData, ActivityFeedEntryData, LogEntry } from "../../api/endpoints";
import { getAppActivity, getRecentLogs } from "../../api/endpoints";
import { useScopedApi } from "../../hooks/use-scoped-api";
import { useApi } from "../../hooks/use-api";
import { useAppState } from "../../state/context";
import { useDebouncedEffect } from "../../hooks/use-debounced-effect";

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
      <div class="ht-overview-tab__section-heading">failing handlers</div>
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
  if (items.length === 0) {
    return (
      <section class="ht-overview-tab__section" data-testid="overview-health-grid">
        <div class="ht-overview-tab__section-heading">handler health</div>
        <EmptyState
          title="No handlers registered"
          body="This app has not registered any event handlers or scheduled jobs."
          data-testid="overview-health-empty"
        />
      </section>
    );
  }

  const sorted = sortedByFailingFirst(items);

  return (
    <section class="ht-overview-tab__section" data-testid="overview-health-grid">
      <div class="ht-overview-tab__section-heading">handler health</div>
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
  return (
    <tr class="ht-overview-activity-row" data-testid="overview-activity-row">
      <td class="ht-overview-activity__status" aria-label={`status: ${entry.status}`}>
        <StatusShape kind={kind} size={8} />
      </td>
      <td class="ht-overview-activity__name">{entry.handler_name}</td>
      <td class="ht-overview-activity__duration">{formatDurationOrDash(entry.duration_ms)}</td>
      <td class="ht-overview-activity__time">{formatRelativeTime(entry.timestamp)}</td>
    </tr>
  );
}

interface RecentActivitySectionProps {
  appKey: string;
  resolvedInstanceIndex: number;
}

function RecentActivitySection({ appKey, resolvedInstanceIndex }: RecentActivitySectionProps) {
  const { data: activity, loading, refetch } = useScopedApi(
    (since) => getAppActivity(appKey, resolvedInstanceIndex, ACTIVITY_LIMIT, since),
    { deps: [appKey, resolvedInstanceIndex] },
  );

  const { invocationCompleted, executionCompleted } = useAppState();

  useDebouncedEffect(
    () => invocationCompleted.value,
    500,
    () => {
      const events = invocationCompleted.value;
      if (!events) return;
      const matches = events.some((e) => e.app_key === appKey);
      if (matches) void refetch();
    },
  );

  useDebouncedEffect(
    () => executionCompleted.value,
    500,
    () => {
      const events = executionCompleted.value;
      if (!events) return;
      const matches = events.some((e) => e.app_key === appKey);
      if (matches) void refetch();
    },
  );

  const entries = activity.value ?? [];

  return (
    <section class="ht-overview-tab__section" data-testid="overview-activity-section">
      <div class="ht-overview-tab__section-heading">recent activity</div>
      {!loading.value && entries.length === 0 ? (
        <p class="ht-overview-empty-inline" data-testid="overview-activity-empty">
          no recent activity
        </p>
      ) : (
        <table class="ht-overview-activity-table">
          <tbody>
            {entries.map((entry) => (
              <ActivityRow key={`${entry.kind}-${entry.handler_name}-${entry.timestamp}`} entry={entry} />
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
  return (
    <tr class="ht-overview-log-row" data-testid="overview-log-row">
      <td class="ht-overview-log__level" aria-label={`level: ${entry.level}`}>
        <StatusShape kind={kind} size={8} />
        <span class="ht-overview-log__level-text">{entry.level}</span>
      </td>
      <td class="ht-overview-log__time">{formatRelativeTime(entry.timestamp)}</td>
      <td class="ht-overview-log__message" title={entry.message}>{entry.message}</td>
    </tr>
  );
}

interface RecentLogsSectionProps {
  appKey: string;
}

function RecentLogsSection({ appKey }: RecentLogsSectionProps) {
  const { data: logs, loading } = useApi(
    () => getRecentLogs({ app_key: appKey, limit: LOGS_LIMIT }),
    [appKey],
  );

  const entries = logs.value ?? [];

  return (
    <section class="ht-overview-tab__section" data-testid="overview-logs-section">
      <div class="ht-overview-tab__section-heading">recent logs</div>
      {!loading.value && entries.length === 0 ? (
        <p class="ht-overview-empty-inline" data-testid="overview-logs-empty">
          no recent logs
        </p>
      ) : (
        <table class="ht-overview-log-table">
          <tbody>
            {entries.map((entry) => (
              <LogRow key={entry.seq ?? `${entry.timestamp}-${entry.logger_name}-${entry.lineno}`} entry={entry} />
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

// ── Overview Tab ──────────────────────────────────────────────────────────────

export function OverviewTab({ listeners, jobs, appKey, instanceQs, resolvedInstanceIndex }: Props) {
  const allItems = buildItems(listeners, jobs);

  const failingItems = allItems.filter(isFailing);

  return (
    <div class="ht-overview-tab" data-testid="overview-tab">
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
