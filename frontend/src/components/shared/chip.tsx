import clsx from "clsx";
import type { JSX } from "preact";

import styles from "./chip.module.css";

export type ChipVariant = "modifier" | "schedule" | "kind" | "origin" | "muted";
export type ChipKind = "ok" | "warn" | "err" | "mute";
export type ChipSize = "default" | "sm";

const kindClassMap: Record<ChipKind, string> = {
  ok: styles.kindOk,
  warn: styles.kindWarn,
  err: styles.kindErr,
  mute: styles.kindMute,
};

interface ChipBaseProps extends JSX.HTMLAttributes<HTMLSpanElement> {
  size?: ChipSize;
  class?: string;
}

type ChipProps =
  | (ChipBaseProps & { variant: "kind"; kind: ChipKind })
  | (ChipBaseProps & { variant: Exclude<ChipVariant, "kind">; kind?: never });

export function Chip({ variant, kind, size = "default", class: className, children, ...rest }: ChipProps) {
  return (
    <span
      data-variant={variant}
      class={clsx(
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
