import clsx from "clsx";
import type { HTMLAttributes } from "react";

import type { StatusVariant } from "../../utils/status";
import styles from "./badge.module.css";

export type BadgeVariant = StatusVariant | "info";
export type BadgeSize = "default" | "xs" | "sm" | "md";

interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  variant: BadgeVariant;
  size?: BadgeSize;
  className?: string;
}

export function Badge({ variant, size = "default", className, children, ...rest }: BadgeProps) {
  return (
    <span className={clsx(styles.badge, styles[variant], size !== "default" && styles[size], className)} {...rest}>
      {children}
    </span>
  );
}
