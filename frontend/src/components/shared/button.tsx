import clsx from "clsx";
import type { JSX } from "preact";

import styles from "./button.module.css";

export type ButtonVariant = "default" | "primary" | "success" | "warning" | "info" | "danger";
export type ButtonSize = "default" | "sm" | "xs";

interface ButtonProps extends Omit<JSX.ButtonHTMLAttributes<HTMLButtonElement>, "type"> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  ghost?: boolean;
  icon?: boolean;
  class?: string;
  /** Callback ref for accessing the underlying <button> DOM element. */
  buttonRef?: (el: HTMLButtonElement | null) => void;
}

export function Button({
  variant = "default",
  size = "default",
  ghost = false,
  icon = false,
  class: className,
  buttonRef,
  children,
  ...rest
}: ButtonProps) {
  return (
    <button
      type="button"
      ref={buttonRef}
      class={clsx(
        styles.btn,
        variant !== "default" && styles[variant],
        size !== "default" && styles[size],
        ghost && styles.ghost,
        icon && styles.icon,
        className,
      )}
      {...rest}
    >
      {children}
    </button>
  );
}
