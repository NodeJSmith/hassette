import clsx from "clsx";
import type { ComponentChildren } from "preact";

import styles from "./tooltip.module.css";

interface TooltipProps {
  label: string;
  class?: string;
  focusable?: boolean;
  children: ComponentChildren;
}

export function Tooltip({ label, class: className, focusable, children }: TooltipProps) {
  return (
    <span class={clsx(styles.trigger, className)} data-tooltip={label} {...(focusable ? { tabIndex: 0 } : {})}>
      <span class={styles.srOnly}>{label}: </span>
      {children}
    </span>
  );
}
