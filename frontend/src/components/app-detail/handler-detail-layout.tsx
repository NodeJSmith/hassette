import type { ComponentChildren } from "preact";

import styles from "./handler-detail-layout.module.css";

interface Props {
  testId: string;
  children: ComponentChildren;
}

export function HandlerDetailLayout({ testId, children }: Props) {
  return (
    <div class={styles.wrapper} data-testid={testId}>
      <div class={styles.content}>{children}</div>
    </div>
  );
}
