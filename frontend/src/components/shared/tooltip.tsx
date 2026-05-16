import type { ComponentChildren } from "preact";
import clsx from "clsx";
import styles from "./tooltip.module.css";

interface TooltipProps {
  label: string;
  class?: string;
  children: ComponentChildren;
}

export function Tooltip({ label, class: className, children }: TooltipProps) {
  return (
    <span class={clsx(styles.trigger, className)} data-tooltip={label}>
      {children}
    </span>
  );
}
