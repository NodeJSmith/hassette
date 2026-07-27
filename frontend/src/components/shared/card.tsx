import clsx from "clsx";
import type { HTMLAttributes, Ref } from "react";

import styles from "./card.module.css";

export type CardVariant = "default" | "compact" | "config" | "error";

interface CardProps extends HTMLAttributes<HTMLDivElement> {
  variant?: CardVariant;
  className?: string;
  /** Ref forwarding via containerRef pattern (following TableCard convention). */
  containerRef?: Ref<HTMLDivElement>;
}

export function Card({ variant = "default", className, containerRef, children, ...rest }: CardProps) {
  // error variant absorbs base card styles — no separate .card class needed.
  // All other variants are additive modifiers on top of the base .card class.
  const isError = variant === "error";

  return (
    <div
      ref={containerRef}
      className={clsx(
        !isError && styles.card,
        isError && styles.error,
        variant === "compact" && styles.compact,
        variant === "config" && styles.config,
        className,
      )}
      {...rest}
    >
      {children}
    </div>
  );
}
