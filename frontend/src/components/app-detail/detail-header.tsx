import type { ComponentChildren } from "preact";

import { Badge } from "../shared/badge";
import { Chip, type ChipKind } from "../shared/chip";
import { StatusShape } from "../shared/status-shape";
import styles from "./detail-header.module.css";

interface DetailHeaderProps {
  name: string;
  kindLabel: string;
  statusKind: ChipKind;
  kind: "handler" | "job";
  subtitle?: string | null;
  headerActions?: ComponentChildren;
}

export function DetailHeader({ name, kindLabel, statusKind, kind, subtitle, headerActions }: DetailHeaderProps) {
  const isFailing = statusKind === "err";

  return (
    <>
      <div class={styles.header}>
        <h2 class={styles.handlerName}>{name}</h2>
        {isFailing && (
          <Badge variant="danger" size="sm" data-testid="handler-status-pill">
            failing
          </Badge>
        )}
        {headerActions && <div class={styles.headerActions}>{headerActions}</div>}
      </div>

      <div class={styles.subtitle}>
        <Chip variant="kind" kind={statusKind} aria-label={`kind: ${kindLabel}`}>
          <StatusShape kind={statusKind} size={8} />
          {kindLabel}
        </Chip>
        {subtitle && <span data-testid={`${kind}-human-description`}>{subtitle}</span>}
      </div>
    </>
  );
}
