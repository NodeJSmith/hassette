import { Badge } from "@/components/ui/badge";

import type { components } from "../../api/generated-types";
import { BADGE_STATUS_DOT_SIZE, HEADING_STATUS_SHAPE_SIZE } from "../../utils/constants";
import { statusToKind, statusToVariant } from "../../utils/status";
import { ActionButtons, getStableInstanceRef } from "../shared/action-buttons";
import { AlertShell } from "../shared/alert-shell";
import { ErrorBanner } from "../shared/error-banner";
import { StatusShape } from "../shared/status-shape";

type AppManifest = components["schemas"]["AppManifestResponse"];
type InstanceInfo = NonNullable<AppManifest["instances"]>[number];
type ManifestStatus = components["schemas"]["ManifestStatus"];
type ResourceStatus = components["schemas"]["ResourceStatus"];

interface Props {
  appKey: string;
  liveStatus: ManifestStatus | ResourceStatus | "unknown";
  manifest: AppManifest | undefined;
  // currentInstance is resolvedInstanceIndex looked up against the manifest's (possibly
  // sparse) instances array — undefined when that lookup misses (e.g. an out-of-range URL
  // query param). resolvedInstanceIndex is display-only (the "instance N" meta text) and
  // always renders even on a miss; currentInstance gates the ActionButtons instance prop
  // below so a miss falls back to app-level actions instead of a blank instance name.
  currentInstance: InstanceInfo | undefined;
  resolvedInstanceIndex: number;
  showParentOverview: boolean;
}

/** Middot-separated chip appended to the subtitle meta line. */
function MetaBadge({ label, testId }: { label: string; testId: string }) {
  return (
    <>
      {" "}
      &middot;{" "}
      <Badge variant="muted" data-testid={testId}>
        {label}
      </Badge>
    </>
  );
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
            <StatusShape kind={statusToKind(liveStatus)} size={HEADING_STATUS_SHAPE_SIZE} />
            <span className="min-w-0 break-all">{appKey}</span>
          </h1>
        </div>
        <div className="flex flex-wrap items-center justify-end gap-2 max-mobile:justify-start">
          {/* Shown for every status, healthy included — "running" should be a
              statement, not the absence of a pill. */}
          <Badge variant={statusToVariant(liveStatus)} size="sm" data-testid="app-status-pill">
            <StatusShape kind={statusToKind(liveStatus)} size={BADGE_STATUS_DOT_SIZE} /> {liveStatus}
          </Badge>
          <ActionButtons
            appKey={appKey}
            status={liveStatus}
            variant="text"
            confirmStop
            {...(manifest && manifest.instance_count > 1 && !showParentOverview && currentInstance
              ? { instance: getStableInstanceRef(currentInstance.index, currentInstance.instance_name) }
              : {})}
          />
        </div>
      </div>

      <p className="mb-3 break-words font-mono text-sm text-muted-foreground" data-testid="app-subtitle-meta">
        {manifest?.filename ?? appKey}
        {manifest?.class_name && manifest.class_name !== appKey && <> &middot; {manifest.class_name}</>}
        {manifest && manifest.instance_count > 1 && !showParentOverview && (
          <> &middot; instance {resolvedInstanceIndex}</>
        )}
        {manifest?.auto_loaded && <MetaBadge label="auto" testId="auto-loaded-badge" />}
        {/* Strict `=== false`, not `!manifest?.autostart`: `manifest` is undefined while
            loading, and we must not flash the chip before the manifest arrives. */}
        {manifest?.autostart === false && <MetaBadge label="no autostart" testId="no-autostart-badge" />}
      </p>

      {errorMsg && (
        <ErrorBanner
          errorMessage={errorMsg}
          traceback={manifest?.error_traceback ?? null}
          data-testid="error-display"
        />
      )}

      {manifest?.block_reason && (
        <AlertShell
          tone="warning"
          className="text-[length:var(--text-body)] text-[var(--status-warning)]"
          role="alert"
          data-testid="block-reason-banner"
        >
          <strong>Blocked:</strong> {manifest.block_reason}
        </AlertShell>
      )}
    </>
  );
}
