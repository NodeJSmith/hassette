import { Badge } from "@/components/ui/badge";

import type { components } from "../../api/generated-types";
import styles from "../../pages/app-detail.module.css";
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
      <div className="ht-level ht-mb-2">
        <div className="ht-level-start">
          <div className="ht-level-item">
            <h1 className={styles.heading4} data-testid="app-title">
              <StatusShape kind={statusToKind(liveStatus)} size={14} />
              <span className="ht-ml-2">{appKey}</span>
            </h1>
          </div>
        </div>
        <div className="ht-level-end">
          {/* Shown for every status, healthy included — "running" should be a
              statement, not the absence of a pill. */}
          <Badge variant={statusToVariant(liveStatus)} size="sm" data-testid="app-status-pill">
            <StatusShape kind={statusToKind(liveStatus)} size={8} /> {liveStatus}
          </Badge>
          <ActionButtons appKey={appKey} status={liveStatus} variant="text" confirmStop />
        </div>
      </div>

      <p className="ht-text-mono ht-text-sm ht-text-muted ht-mb-3" data-testid="app-subtitle-meta">
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
        <div className="ht-alert ht-alert--warning ht-mb-4" role="alert" data-testid="block-reason-banner">
          <strong>Blocked:</strong> {manifest.block_reason}
        </div>
      )}
    </>
  );
}
