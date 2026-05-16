import type { JSX } from "preact";
import clsx from "clsx";
import styles from "./tooltip.module.css";

interface TooltipProps {
  label: string;
  class?: string;
  children: JSX.Element | JSX.Element[];
}

export function Tooltip({ label, class: className, children }: TooltipProps) {
  return (
    <span class={clsx(styles.trigger, className)} data-tooltip={label}>
      {children}
    </span>
  );
}
