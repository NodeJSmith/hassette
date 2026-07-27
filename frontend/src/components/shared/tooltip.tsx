import clsx from "clsx";
import type { ReactNode } from "react";

import styles from "./tooltip.module.css";

interface TooltipProps {
  label: string;
  className?: string;
  focusable?: boolean;
  children: ReactNode;
}

export function Tooltip({ label, className, focusable, children }: TooltipProps) {
  return (
    <span className={clsx(styles.trigger, className)} data-tooltip={label} {...(focusable ? { tabIndex: 0 } : {})}>
      <span className={styles.srOnly}>{label}: </span>
      {children}
    </span>
  );
}
