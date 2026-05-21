import clsx from "clsx";
import type { ComponentChildren } from "preact";

import { LogDetailDrawer } from "./log-detail-drawer";
import styles from "./log-table.module.css";
import type { LogDrawerProps } from "./use-log-table";

interface Props {
  drawerProps: LogDrawerProps;
  children: ComponentChildren;
}

export function LogTableWithDrawer({ drawerProps, children }: Props) {
  const open = drawerProps.selectedKey !== null;
  return (
    <div class={clsx(styles.wrapper, open && styles.drawerOpen)}>
      <div class={styles.tableArea}>{children}</div>
      <LogDetailDrawer
        selectedKey={drawerProps.selectedKey}
        entries={drawerProps.entries}
        onClose={drawerProps.onClose}
        onNavigate={drawerProps.onNavigate}
      />
    </div>
  );
}
