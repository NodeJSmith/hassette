import clsx from "clsx";
import type { HTMLAttributes } from "react";

import type { StatusKind } from "../../utils/status";
import styles from "./chip.module.css";

export type ChipVariant = "job" | "listener" | "kind" | "origin" | "muted";
export type ChipKind = StatusKind;
export type ChipSize = "default" | "sm";

const kindClassMap: Record<ChipKind, string> = {
  ok: styles.kindOk,
  warn: styles.kindWarn,
  err: styles.kindErr,
  cancel: styles.kindCancel,
  mute: styles.kindMute,
};

interface ChipBaseProps extends HTMLAttributes<HTMLSpanElement> {
  size?: ChipSize;
  className?: string;
}

type ChipProps =
  | (ChipBaseProps & { variant: "kind"; kind: ChipKind })
  | (ChipBaseProps & { variant: Exclude<ChipVariant, "kind">; kind?: never });

export function Chip({ variant, kind, size = "default", className, children, ...rest }: ChipProps) {
  return (
    <span
      data-variant={variant}
      className={clsx(
        styles.chip,
        variant !== "kind" && styles[variant],
        variant === "kind" && styles.kind,
        variant === "kind" && kind && kindClassMap[kind],
        size !== "default" && styles.sm,
        className,
      )}
      {...rest}
    >
      {children}
    </span>
  );
}
