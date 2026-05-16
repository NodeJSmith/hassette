import type { JSX } from "preact";
import styles from "./tooltip.module.css";

interface TooltipProps {
  label: string;
  children: JSX.Element | JSX.Element[];
}

export function Tooltip({ label, children }: TooltipProps) {
  return (
    <span class={styles.trigger} data-tooltip={label}>
      {children}
    </span>
  );
}
