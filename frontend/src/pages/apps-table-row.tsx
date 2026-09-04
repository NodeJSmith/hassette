import type { MouseEvent as ReactMouseEvent } from "react";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

import { ActionButtons, getStableInstanceRef } from "../components/shared/action-buttons";
import { AppLink } from "../components/shared/app-link";
import { IconChevron } from "../components/shared/icons";
import { MiniSparkline } from "../components/shared/mini-sparkline";
import { StatusShape } from "../components/shared/status-shape";
import { useRelativeTime } from "../hooks/use-relative-time";
import type { AppStatusEntry } from "../state/store";
import { appLiveStatus, type AppRow, instanceLiveError, instanceLiveStatus } from "../utils/app-data";
import { APP_ROW_STATUS_SHAPE_SIZE, INSTANCE_ROW_STATUS_SHAPE_SIZE } from "../utils/constants";
import { formatTimestamp } from "../utils/format";
import { onActivateKeyDown } from "../utils/keyboard";
import { INACTIVE_STATUSES, statusToKind, statusToVariant } from "../utils/status";

export function AppTableRow({
  app,
  appStatuses,
  isExpanded,
  onToggle,
  muteStatus = false,
  compact = false,
}: {
  app: AppRow;
  appStatuses: Record<string, AppStatusEntry>;
  isExpanded: boolean;
  onToggle: () => void;
  muteStatus?: boolean;
  compact?: boolean;
}) {
  const [errorExpanded, setErrorExpanded] = useState(false);
  const showErrorExpanded = errorExpanded && !!app.error_message;
  const lastErrorLabel = useRelativeTime(app.last_error_ts ?? null);
  const lastActivityLabel = useRelativeTime(app.last_activity_ts ?? null);
  const status = appLiveStatus(appStatuses, app);
  const kind = statusToKind(status);
  const isMulti = app.instance_count > 1;
  const isDimmed = INACTIVE_STATUSES.has(status);
  const totalRuns = app.total_invocations + app.total_executions;

  return (
    <>
      <tr
        className={cn(
          "group transition-colors max-mobile:active:bg-accent",
          isDimmed && "opacity-[var(--opacity-disabled)]",
        )}
        data-state={isDimmed ? "inactive" : "active"}
        data-testid={`app-row-${app.app_key}`}
      >
        {/* Name */}
        <td className="min-w-0">
          <div className="flex min-w-0 items-center gap-2 [&_a]:min-w-0 [&_a]:overflow-hidden [&_a]:text-ellipsis [&_a]:whitespace-nowrap max-sidebar:after:ml-auto max-sidebar:after:text-[length:var(--text-h3)] max-sidebar:after:text-foreground-faint max-sidebar:after:content-['›']">
            <span className="flex w-4 shrink-0 items-center justify-center">
              {isMulti && (
                <button
                  type="button"
                  className="w-4 cursor-pointer border-0 bg-transparent p-0 text-[length:var(--text-mono-md)] leading-none text-foreground-secondary focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary max-sidebar:flex max-sidebar:min-h-[var(--sz-touch)] max-sidebar:min-w-[var(--sz-touch)] max-sidebar:items-center max-sidebar:justify-center"
                  onClick={onToggle}
                  aria-expanded={isExpanded}
                  aria-label={`${isExpanded ? "Collapse" : "Expand"} ${app.app_key}`}
                  data-testid="app-row-expand"
                >
                  <IconChevron open={isExpanded} />
                </button>
              )}
            </span>
            <StatusShape kind={kind} size={APP_ROW_STATUS_SHAPE_SIZE} muted={muteStatus} />
            <AppLink appKey={app.app_key}>{app.display_name}</AppLink>
            <span className={cn("text-xs text-muted-foreground max-sidebar:hidden", compact && "hidden")}>
              {app.class_name}
            </span>
            {app.auto_loaded && (
              <Badge variant="muted" className={cn("max-sidebar:hidden", compact && "hidden")}>
                auto
              </Badge>
            )}
            {!app.autostart && (
              <Badge
                variant="muted"
                className={cn("max-sidebar:hidden", compact && "hidden")}
                data-testid="no-autostart-chip"
              >
                no autostart
              </Badge>
            )}
            {!app.in_current_config && (
              <Badge
                variant="muted"
                className={cn("max-sidebar:hidden", compact && "hidden")}
                data-testid="removed-chip"
              >
                removed
              </Badge>
            )}
          </div>
        </td>
        {/* Status */}
        <td>
          <Badge variant={statusToVariant(status)} size="sm" data-testid="status-pill">
            {status}
          </Badge>
          {isMulti && (
            <span
              className={cn("ml-1 font-mono text-xs text-muted-foreground max-sidebar:hidden", compact && "hidden")}
            >
              {app.instance_count} instances
            </span>
          )}
        </td>
        {/* Error */}
        <td
          className={cn(
            "max-w-[200px] cursor-default whitespace-nowrap max-sidebar:hidden",
            compact && "hidden",
            showErrorExpanded && "max-w-none break-words whitespace-normal",
          )}
          {...(app.error_message
            ? {
                role: "button",
                tabIndex: 0,
                "aria-label": `${showErrorExpanded ? "Collapse" : "Expand"} error: ${app.error_message}`,
                onClick: (e: ReactMouseEvent) => {
                  e.stopPropagation();
                  setErrorExpanded(!errorExpanded);
                },
                onKeyDown: onActivateKeyDown(() => setErrorExpanded(!errorExpanded)),
              }
            : {})}
        >
          {app.error_message ? (
            <span className="font-mono text-sm text-destructive">
              {app.error_message}
              {app.last_error_ts && <span className="text-muted-foreground"> · {lastErrorLabel}</span>}
            </span>
          ) : (
            "—"
          )}
        </td>
        {/* Runs + sparkline */}
        <td className={cn("align-middle text-right max-sidebar:hidden", compact && "hidden")}>
          <div className="inline-flex items-center gap-2">
            <MiniSparkline buckets={app.activity_buckets} height={16} />
            <span className="font-mono">{totalRuns}</span>
          </div>
        </td>
        {/* Last fired */}
        <td className={cn("font-mono text-sm text-muted-foreground max-sidebar:hidden", compact && "hidden")}>
          {app.last_activity_ts ? <span title={formatTimestamp(app.last_activity_ts)}>{lastActivityLabel}</span> : "—"}
        </td>
        {/* Actions */}
        <td
          className={cn(
            "text-right max-sidebar:hidden [&_[data-role='action-buttons']]:justify-end [&_[data-role='action-buttons']]:opacity-[var(--opacity-ghost)] [&_[data-role='action-buttons']]:transition-opacity group-hover:[&_[data-role='action-buttons']]:opacity-100",
            compact && "hidden",
          )}
        >
          <ActionButtons appKey={app.app_key} status={status} confirmStop />
        </td>
      </tr>
      {isMulti &&
        isExpanded &&
        app.instances?.map((inst) => {
          const instStatus = instanceLiveStatus(appStatuses, app.app_key, inst);
          const instErrorMessage = instanceLiveError(appStatuses, app.app_key, inst);
          const instKind = statusToKind(instStatus);
          // A blocked parent's not-yet-tracked instances still report a synthetic "stopped"
          // status (see build_manifest_info()) so they stay addressable in the table — but
          // that makes CAN_START key off "stopped" and show a Start button for an app the
          // exclusive-app filter excluded. Force the action status to "blocked" in that case;
          // the backend guards it too (AppLifecycleService rejects starts for blocked apps).
          //
          // Deliberately narrower than appLiveStatus()'s "disabled" | "blocked" override
          // (configStatusOverride): the backend explicitly permits a transient start of a
          // disabled app's instance (CAN_START.disabled is true on purpose), so once that
          // instance is actually running, this must reflect its live status — not freeze on
          // "disabled" and hide Stop/Reload forever. "blocked" has no such transient-start
          // path; the backend rejects it outright, so the override never goes stale.
          const instActionStatus = status === "blocked" ? "blocked" : instStatus;
          return (
            <tr
              key={`${app.app_key}-${inst.index}`}
              className="group bg-background transition-colors hover:bg-muted max-mobile:active:bg-accent"
              data-testid={`instance-row-${app.app_key}-${inst.index}`}
            >
              <td className="min-w-0">
                <div className="flex min-w-0 items-center gap-2 [&_a]:min-w-0 [&_a]:overflow-hidden [&_a]:text-ellipsis [&_a]:whitespace-nowrap max-sidebar:after:ml-auto max-sidebar:after:text-[length:var(--text-h3)] max-sidebar:after:text-foreground-faint max-sidebar:after:content-['›']">
                  <span className="ml-[calc(var(--spacing-4)+var(--spacing-0-5))] text-xs text-foreground-faint">
                    └
                  </span>
                  <StatusShape kind={instKind} size={INSTANCE_ROW_STATUS_SHAPE_SIZE} muted={muteStatus} />
                  <AppLink appKey={app.app_key} instanceIndex={inst.index}>
                    {inst.instance_name}
                  </AppLink>
                </div>
              </td>
              <td>
                <Badge variant={statusToVariant(instStatus)} size="sm">
                  {instStatus}
                </Badge>
              </td>
              <td
                className={cn("max-w-[200px] cursor-default whitespace-nowrap max-sidebar:hidden", compact && "hidden")}
              >
                {instErrorMessage ? (
                  <span className="font-mono text-sm text-destructive" title={instErrorMessage}>
                    {instErrorMessage}
                  </span>
                ) : (
                  "—"
                )}
              </td>
              <td className={cn("max-sidebar:hidden", compact && "hidden")} />
              <td className={cn("max-sidebar:hidden", compact && "hidden")} />
              <td
                className={cn(
                  "text-right max-sidebar:hidden [&_[data-role='action-buttons']]:justify-end [&_[data-role='action-buttons']]:opacity-[var(--opacity-ghost)] [&_[data-role='action-buttons']]:transition-opacity group-hover:[&_[data-role='action-buttons']]:opacity-100",
                  compact && "hidden",
                )}
              >
                <ActionButtons
                  appKey={app.app_key}
                  status={instActionStatus}
                  confirmStop
                  instance={getStableInstanceRef(inst.index, inst.instance_name)}
                />
              </td>
            </tr>
          );
        })}
    </>
  );
}
