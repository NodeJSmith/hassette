import type { ReactNode } from "react";

import { Badge, type BadgeVariant } from "@/components/ui/badge";

import type { StatusKind } from "../../utils/status";
import type { ExecutionKind } from "../shared/execution-table";
import { StatusShape } from "../shared/status-shape";

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
  kind: ExecutionKind;
  subtitle?: string | null;
  headerActions?: ReactNode;
}

export function DetailHeader({ name, kindLabel, statusKind, kind, subtitle, headerActions }: DetailHeaderProps) {
  const isFailing = statusKind === "err";

  return (
    <>
      <div className="mb-3 flex flex-wrap items-baseline gap-2">
        <h2 className="font-mono text-[length:var(--text-h2)] font-semibold text-foreground">{name}</h2>
        {isFailing && (
          <Badge variant="danger" size="sm" data-testid={`${kind}-status-pill`}>
            failing
          </Badge>
        )}
        {headerActions && <div className="ml-auto flex items-center gap-2">{headerActions}</div>}
      </div>

      <div className="mb-3 flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
        <Badge variant={KIND_BADGE_VARIANT[statusKind]} aria-label={`kind: ${kindLabel}`}>
          <StatusShape kind={statusKind} size={8} />
          {kindLabel}
        </Badge>
        {subtitle && <span data-testid={`${kind}-human-description`}>{subtitle}</span>}
      </div>
    </>
  );
}
