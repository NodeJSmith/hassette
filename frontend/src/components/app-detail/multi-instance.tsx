import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

import type { AppInstance } from "../../api/endpoints";
import { useAppStore } from "../../state/store";
import { instanceLiveStatus } from "../../utils/app-data";
import { BADGE_STATUS_DOT_SIZE, STATUS_DOT_SIZE } from "../../utils/constants";
import { statusToKind, statusToVariant } from "../../utils/status";
import { StatusShape } from "../shared/status-shape";

export function InstanceSwitcher({
  appKey,
  instances,
  currentIndex,
  onNavigate,
}: {
  appKey: string;
  instances: AppInstance[];
  currentIndex: number;
  onNavigate: (index: number) => void;
}) {
  const appStatus = useAppStore((s) => s.appStatus);

  return (
    <div
      className="flex flex-wrap items-center gap-1"
      data-testid="instance-switcher"
      role="tablist"
      aria-label="Instance"
    >
      {instances.map((instance) => {
        const isActive = instance.index === currentIndex;
        const liveStatus = instanceLiveStatus(appStatus, appKey, instance);
        return (
          <button
            key={instance.index}
            type="button"
            role="tab"
            aria-selected={isActive}
            className={cn(
              "inline-flex items-center gap-2 whitespace-nowrap rounded-sm border border-border bg-transparent px-3 py-1 font-mono text-xs text-foreground-secondary transition-colors hover:bg-accent hover:text-foreground focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary",
              isActive &&
                "cursor-default border-[var(--primary-border)] bg-[var(--primary-bg)] font-medium text-primary hover:bg-[var(--primary-bg)] hover:text-primary",
            )}
            data-testid={`switcher-instance-${instance.index}`}
            onClick={() => {
              if (!isActive) onNavigate(instance.index);
            }}
          >
            <StatusShape kind={statusToKind(liveStatus)} size={BADGE_STATUS_DOT_SIZE} />
            <span className="max-w-[140px] overflow-hidden text-ellipsis">{instance.instance_name}</span>
          </button>
        );
      })}
    </div>
  );
}

function InstanceCard({
  instance,
  liveStatus,
  onNavigate,
}: {
  instance: AppInstance;
  liveStatus: AppInstance["status"];
  onNavigate: (index: number) => void;
}) {
  return (
    <button
      type="button"
      className="flex cursor-pointer flex-col gap-2 rounded-md border border-[var(--border-strong)] bg-card p-4 text-left font-inherit text-sm text-foreground shadow-[var(--shadow-2)] transition-[border-color,box-shadow] hover:shadow-[var(--shadow-3)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary"
      data-testid={`instance-card-${instance.index}`}
      onClick={() => {
        onNavigate(instance.index);
      }}
      aria-label={`View ${instance.instance_name}`}
    >
      <div className="flex flex-wrap items-center gap-2">
        <StatusShape kind={statusToKind(liveStatus)} size={STATUS_DOT_SIZE} />
        <span className="min-w-0 flex-1 overflow-hidden text-ellipsis whitespace-nowrap font-medium">
          {instance.instance_name}
        </span>
        <Badge variant={statusToVariant(liveStatus)} size="sm" className="ml-auto shrink-0">
          {liveStatus}
        </Badge>
      </div>
      {instance.error_message && (
        <p className="overflow-hidden text-ellipsis whitespace-nowrap text-xs text-destructive italic">
          {instance.error_message}
        </p>
      )}
    </button>
  );
}

export function MultiInstanceOverview({
  appKey,
  displayName,
  instances,
  instanceCount,
  onNavigate,
}: {
  appKey: string;
  displayName: string;
  instances: AppInstance[];
  instanceCount: number;
  onNavigate: (index: number) => void;
}) {
  const appStatus = useAppStore((s) => s.appStatus);

  return (
    <div className="py-4" data-testid="multi-instance-overview">
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="flex items-center gap-[0.35em] font-sans text-[length:var(--text-h2)] font-semibold max-mobile:text-[length:var(--text-body)]">
            {displayName}
          </h2>
          <Badge variant="neutral" data-testid="instance-count-badge">
            ×{instanceCount} instances
          </Badge>
        </div>
      </div>
      <code className="mb-4 block font-mono text-sm">{appKey}</code>
      <div className="grid grid-cols-[repeat(auto-fill,minmax(280px,1fr))] gap-4" data-testid="instance-grid">
        {instances.map((instance) => (
          <InstanceCard
            key={instance.index}
            instance={instance}
            liveStatus={instanceLiveStatus(appStatus, appKey, instance)}
            onNavigate={onNavigate}
          />
        ))}
      </div>
    </div>
  );
}
