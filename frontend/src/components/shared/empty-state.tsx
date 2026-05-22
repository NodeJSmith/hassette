import styles from "./empty-state.module.css";

interface EmptyStateProps {
  icon?: string;
  title: string;
  body?: string;
  "data-testid"?: string;
  children?: preact.ComponentChildren;
}

export function EmptyState({ icon = "∅", title, body, "data-testid": testId, children }: EmptyStateProps) {
  return (
    <div class={styles.empty} data-testid={testId}>
      {icon && <div class={styles.icon}>{icon}</div>}
      <div class={styles.title}>{title}</div>
      {body && <div class={styles.body}>{body}</div>}
      {children}
    </div>
  );
}
