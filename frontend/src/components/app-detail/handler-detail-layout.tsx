import type { ReactNode } from "react";

import styles from "./handler-detail-layout.module.css";

interface Props {
  testId: string;
  children: ReactNode;
}

export function HandlerDetailLayout({ testId, children }: Props) {
  return (
    <div className={styles.wrapper} data-testid={testId}>
      <div className={styles.content}>{children}</div>
    </div>
  );
}
