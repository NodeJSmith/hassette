import clsx from "clsx";
import type { ButtonHTMLAttributes, Ref } from "react";

import styles from "./button.module.css";

export type ButtonVariant = "default" | "primary" | "success" | "warning" | "info" | "danger";
export type ButtonSize = "default" | "sm" | "xs";

interface ButtonProps extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, "type"> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  ghost?: boolean;
  icon?: boolean;
  className?: string;
  buttonRef?: Ref<HTMLButtonElement>;
}

export function Button({
  variant = "default",
  size = "default",
  ghost = false,
  icon = false,
  className,
  buttonRef,
  children,
  ...rest
}: ButtonProps) {
  return (
    <button
      type="button"
      ref={buttonRef}
      className={clsx(
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
