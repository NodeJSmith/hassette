import clsx from "clsx";

import type { AppInstance } from "../../api/endpoints";
import styles from "../../pages/app-detail.module.css";
import { STATUS_DOT_SIZE } from "../../utils/constants";
import { statusToKind, statusToVariant } from "../../utils/status";
import { Badge } from "../shared/badge";
import { StatusShape } from "../shared/status-shape";

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
    <div className={styles.instanceSwitcher} data-testid="instance-switcher" role="tablist" aria-label="Instance">
      {instances.map((inst) => {
        const isActive = inst.index === currentIndex;
        return (
          <button
            key={inst.index}
            type="button"
            role="tab"
            aria-selected={isActive}
            className={clsx(styles.instanceSwitcherBtn, isActive && styles.instanceSwitcherBtnActive)}
            data-testid={`switcher-instance-${inst.index}`}
            onClick={() => {
              if (!isActive) onNavigate(inst.index);
            }}
          >
            <StatusShape kind={statusToKind(inst.status)} size={8} />
            <span className={styles.instanceSwitcherLabel}>{inst.instance_name}</span>
          </button>
        );
      })}
    </div>
  );
}

function InstanceCard({ instance, onNavigate }: { instance: AppInstance; onNavigate: (index: number) => void }) {
  return (
    <button
      type="button"
      className={styles.instanceCard}
      data-testid={`instance-card-${instance.index}`}
      onClick={() => {
        onNavigate(instance.index);
      }}
      aria-label={`View ${instance.instance_name}`}
    >
      <div className={styles.instanceCardHeader}>
        <StatusShape kind={statusToKind(instance.status)} size={STATUS_DOT_SIZE} />
        <span className={styles.instanceCardName}>{instance.instance_name}</span>
        <Badge variant={statusToVariant(instance.status)} size="sm" className={styles.instanceCardStatusBadge}>
          {instance.status}
        </Badge>
      </div>
      {instance.error_message && <p className={styles.instanceCardErrorPreview}>{instance.error_message}</p>}
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
    <div className={styles.multiOverview} data-testid="multi-instance-overview">
      <div className="ht-level ht-mb-4">
        <div className="ht-level-start">
          <h2 className={styles.heading4}>{displayName}</h2>
          <Badge variant="neutral" data-testid="instance-count-badge">
            ×{instanceCount} instances
          </Badge>
        </div>
      </div>
      <code className="ht-text-mono ht-text-sm ht-mb-4 ht-block">{appKey}</code>
      <div className={styles.instanceGrid} data-testid="instance-grid">
        {instances.map((inst) => (
          <InstanceCard key={inst.index} instance={inst} onNavigate={onNavigate} />
        ))}
      </div>
    </div>
  );
}
