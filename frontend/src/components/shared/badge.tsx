import clsx from "clsx";
import type { JSX } from "preact";
import type { StatusVariant } from "../../utils/status";
import styles from "./badge.module.css";

export type BadgeVariant = StatusVariant | "info";
export type BadgeSize = "default" | "xs" | "sm" | "md";

interface BadgeProps extends JSX.HTMLAttributes<HTMLSpanElement> {
  variant: BadgeVariant;
  size?: BadgeSize;
  class?: string;
}

export function Badge({
  variant,
  size = "default",
  class: className,
  children,
  ...rest
}: BadgeProps) {
  return (
    <span
      class={clsx(
        styles.badge,
        styles[variant],
        size !== "default" && styles[size],
        className,
      )}
      {...rest}
    >
      {children}
    </span>
  );
}
