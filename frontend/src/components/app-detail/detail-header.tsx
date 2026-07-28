import type { ReactNode } from "react";

import { Badge, type BadgeVariant } from "@/components/ui/badge";

import type { StatusKind } from "../../utils/status";
import { StatusShape } from "../shared/status-shape";
import styles from "./detail-header.module.css";

// Maps a StatusKind onto the flattened "kind-*" Badge variants (formerly Chip's
// variant="kind" kind={ChipKind} discriminated union).
const KIND_BADGE_VARIANT: Record<StatusKind, BadgeVariant> = {
  ok: "kind-ok",
  warn: "kind-warn",
  err: "kind-err",
  cancel: "kind-cancel",
  mute: "kind-mute",
};

interface DetailHeaderProps {
  name: string;
  kindLabel: string;
  statusKind: StatusKind;
  kind: "handler" | "job";
  subtitle?: string | null;
  headerActions?: ReactNode;
}

export function DetailHeader({ name, kindLabel, statusKind, kind, subtitle, headerActions }: DetailHeaderProps) {
  const isFailing = statusKind === "err";

  return (
    <>
      <div className={styles.header}>
        <h2 className={styles.handlerName}>{name}</h2>
        {isFailing && (
          <Badge variant="danger" size="sm" data-testid="handler-status-pill">
            failing
          </Badge>
        )}
        {headerActions && <div className={styles.headerActions}>{headerActions}</div>}
      </div>

      <div className={styles.subtitle}>
        <Badge variant={KIND_BADGE_VARIANT[statusKind]} aria-label={`kind: ${kindLabel}`}>
          <StatusShape kind={statusKind} size={8} />
          {kindLabel}
        </Badge>
        {subtitle && <span data-testid={`${kind}-human-description`}>{subtitle}</span>}
      </div>
    </>
  );
}
