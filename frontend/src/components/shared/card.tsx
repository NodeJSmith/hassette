import clsx from "clsx";
import type { JSX } from "preact";

import styles from "./card.module.css";

export type CardVariant = "default" | "compact" | "config" | "error";

interface CardProps extends JSX.HTMLAttributes<HTMLDivElement> {
  variant?: CardVariant;
  class?: string;
  /** Ref forwarding via containerRef pattern (following TableCard convention). */
  containerRef?: preact.Ref<HTMLDivElement>;
}

export function Card({ variant = "default", class: className, containerRef, children, ...rest }: CardProps) {
  // error variant absorbs base card styles — no separate .card class needed.
  // All other variants are additive modifiers on top of the base .card class.
  const isError = variant === "error";

  return (
    <div
      ref={containerRef}
      class={clsx(
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
