import { ActionButtons } from "../shared/action-buttons";
import { ErrorBanner } from "../shared/error-banner";
import { StatusShape } from "../shared/status-shape";
import { Badge } from "../shared/badge";
import { Chip } from "../shared/chip";
import { statusToKind, statusToVariant } from "../../utils/status";
import type { components } from "../../api/generated-types";
import styles from "../../pages/app-detail.module.css";

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
  const showStatusBadge = liveStatus !== "running" && liveStatus !== "starting";
  const errorMsg = currentInstance?.error_message ?? manifest?.error_message ?? null;

  return (
    <>
      <div class="ht-level ht-mb-2">
        <div class="ht-level-start">
          <div class="ht-level-item">
            <h1 class={styles.heading4} data-testid="app-title">
              <StatusShape kind={statusToKind(liveStatus)} size={14} />
              <span class="ht-ml-2">{appKey}</span>
            </h1>
          </div>
        </div>
        <div class="ht-level-end">
          {showStatusBadge && (
            <Badge variant={statusToVariant(liveStatus)} size="sm" data-testid="app-status-pill">
              <StatusShape kind={statusToKind(liveStatus)} size={8} /> {liveStatus}
            </Badge>
          )}
          <ActionButtons appKey={appKey} status={liveStatus} variant="text" confirmStop />
        </div>
      </div>

      <p class="ht-text-mono ht-text-sm ht-text-muted ht-mb-3" data-testid="app-subtitle-meta">
        {manifest?.filename ?? appKey}
        {manifest?.class_name && manifest.class_name !== appKey && (
          <> &middot; {manifest.class_name}</>
        )}
        {manifest && manifest.instance_count > 1 && !showParentOverview && (
          <> &middot; instance {resolvedInstanceIndex}</>
        )}
        {manifest?.auto_loaded && (
          <> &middot; <Chip variant="muted" data-testid="auto-loaded-badge">auto</Chip></>
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
        <div class="ht-alert ht-alert--warning ht-mb-4" role="alert" data-testid="block-reason-banner">
          <strong>Blocked:</strong> {manifest.block_reason}
        </div>
      )}
    </>
  );
}
