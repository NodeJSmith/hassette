import { Badge } from "@/components/ui/badge";

import type { components } from "../../api/generated-types";
import { statusToKind, statusToVariant } from "../../utils/status";
import { ActionButtons } from "../shared/action-buttons";
import { ErrorBanner } from "../shared/error-banner";
import { StatusShape } from "../shared/status-shape";

type AppManifest = components["schemas"]["AppManifestResponse"];
type InstanceInfo = NonNullable<AppManifest["instances"]>[number];

interface Props {
  appKey: string;
  liveStatus: string;
  manifest: AppManifest | undefined;
  currentInstance: InstanceInfo | undefined;
  resolvedInstanceIndex: number;
  showParentOverview: boolean;
}

export function AppDetailHeader({
  appKey,
  liveStatus,
  manifest,
  currentInstance,
  resolvedInstanceIndex,
  showParentOverview,
}: Props) {
  const errorMsg = currentInstance?.error_message ?? manifest?.error_message ?? null;

  return (
    <>
      <div className="mb-2 flex flex-wrap items-start justify-between gap-3 max-mobile:flex-col">
        <div className="min-w-0 flex-1">
          <h1
            className="flex min-w-0 items-start gap-[0.35em] font-sans text-[length:var(--text-h2)] leading-tight font-semibold max-mobile:text-[length:var(--text-body)]"
            data-testid="app-title"
          >
            <StatusShape kind={statusToKind(liveStatus)} size={14} />
            <span className="ml-2 min-w-0 break-all">{appKey}</span>
          </h1>
        </div>
        <div className="flex flex-wrap items-center justify-end gap-2 max-mobile:justify-start">
          {/* Shown for every status, healthy included — "running" should be a
              statement, not the absence of a pill. */}
          <Badge variant={statusToVariant(liveStatus)} size="sm" data-testid="app-status-pill">
            <StatusShape kind={statusToKind(liveStatus)} size={8} /> {liveStatus}
          </Badge>
          <ActionButtons appKey={appKey} status={liveStatus} variant="text" confirmStop />
        </div>
      </div>

      <p className="mb-3 break-words font-mono text-sm text-muted-foreground" data-testid="app-subtitle-meta">
        {manifest?.filename ?? appKey}
        {manifest?.class_name && manifest.class_name !== appKey && <> &middot; {manifest.class_name}</>}
        {manifest && manifest.instance_count > 1 && !showParentOverview && (
          <> &middot; instance {resolvedInstanceIndex}</>
        )}
        {manifest?.auto_loaded && (
          <>
            {" "}
            &middot;{" "}
            <Badge variant="muted" data-testid="auto-loaded-badge">
              auto
            </Badge>
          </>
        )}
        {/* Strict `=== false`, not `!manifest?.autostart`: `manifest` is undefined while
            loading, and we must not flash the chip before the manifest arrives. */}
        {manifest?.autostart === false && (
          <>
            {" "}
            &middot;{" "}
            <Badge variant="muted" data-testid="no-autostart-badge">
              no autostart
            </Badge>
          </>
        )}
      </p>

      {errorMsg && (
        <ErrorBanner
          errorMessage={errorMsg}
          traceback={manifest?.error_traceback ?? null}
          data-testid="error-display"
        />
      )}

      {manifest?.block_reason && (
        <div
          className="mb-4 rounded-md border border-[var(--status-warning)] bg-[var(--status-warning-bg)] px-4 py-3 text-[length:var(--text-body)] text-[var(--status-warning)]"
          role="alert"
          data-testid="block-reason-banner"
        >
          <strong>Blocked:</strong> {manifest.block_reason}
        </div>
      )}
    </>
  );
}
