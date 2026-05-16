import clsx from "clsx";
import type { AppInstance } from "../../api/endpoints";
import { statusToKind, statusToVariant } from "../../utils/status";
import { StatusShape } from "../shared/status-shape";
import { Badge } from "../shared/badge";
import styles from "../../pages/app-detail.module.css";

export function InstanceSwitcher({
  instances,
  currentIndex,
  onNavigate,
}: {
  instances: AppInstance[];
  currentIndex: number;
  onNavigate: (index: number) => void;
}) {
  return (
    <div class={styles.instanceSwitcher} data-testid="instance-switcher" role="tablist" aria-label="Instance">
      {instances.map((inst) => {
        const isActive = inst.index === currentIndex;
        return (
          <button
            key={inst.index}
            type="button"
            role="tab"
            aria-selected={isActive}
            class={clsx(styles.instanceSwitcherBtn, isActive && styles.instanceSwitcherBtnActive)}
            data-testid={`switcher-instance-${inst.index}`}
            onClick={() => { if (!isActive) onNavigate(inst.index); }}
          >
            <StatusShape kind={statusToKind(inst.status)} size={8} />
            <span class={styles.instanceSwitcherLabel}>{inst.instance_name}</span>
          </button>
        );
      })}
    </div>
  );
}

function InstanceCard({
  instance,
  onNavigate,
}: {
  instance: AppInstance;
  onNavigate: (index: number) => void;
}) {
  return (
    <button
      type="button"
      class={styles.instanceCard}
      data-testid={`instance-card-${instance.index}`}
      onClick={() => { onNavigate(instance.index); }}
      aria-label={`View ${instance.instance_name}`}
    >
      <div class={styles.instanceCardHeader}>
        <StatusShape kind={statusToKind(instance.status)} size={10} />
        <span class={styles.instanceCardName}>{instance.instance_name}</span>
        <Badge variant={statusToVariant(instance.status)} size="sm" class={styles.instanceCardStatusBadge}>
          {instance.status}
        </Badge>
      </div>
      {instance.error_message && (
        <p class={styles.instanceCardErrorPreview}>{instance.error_message}</p>
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
  return (
    <div class={styles.multiOverview} data-testid="multi-instance-overview">
      <div class="ht-level ht-mb-4">
        <div class="ht-level-start">
          <h2 class={styles.heading4}>{displayName}</h2>
          <Badge variant="neutral" data-testid="instance-count-badge">
            ×{instanceCount} instances
          </Badge>
        </div>
      </div>
      <code class="ht-text-mono ht-text-sm ht-mb-4 ht-block">{appKey}</code>
      <div class={styles.instanceGrid} data-testid="instance-grid">
        {instances.map((inst) => (
          <InstanceCard
            key={inst.index}
            instance={inst}
            onNavigate={onNavigate}
          />
        ))}
      </div>
    </div>
  );
}
