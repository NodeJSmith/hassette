import type { ReactNode } from "react";

import styles from "./empty-state.module.css";

interface EmptyStateProps {
  icon?: string;
  title: string;
  body?: string;
  "data-testid"?: string;
  children?: ReactNode;
}

export function EmptyState({ icon = "∅", title, body, "data-testid": testId, children }: EmptyStateProps) {
  return (
    <div className={styles.empty} data-testid={testId}>
      {icon && <div className={styles.icon}>{icon}</div>}
      <div className={styles.title}>{title}</div>
      {body && <div className={styles.body}>{body}</div>}
      {children}
    </div>
  );
}
