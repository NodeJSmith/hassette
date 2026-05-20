import clsx from "clsx";
import { Link } from "wouter";

import styles from "../../pages/app-detail.module.css";

interface Props {
  appKey: string;
  isMultiInstance: boolean;
  showParentOverview: boolean;
  instanceName: string;
}

export function AppDetailBreadcrumb({ appKey, isMultiInstance, showParentOverview, instanceName }: Props) {
  return (
    <nav class={clsx(styles.breadcrumb, "ht-mb-3")} aria-label="Breadcrumb">
      <Link href="/apps">apps</Link>
      <span class={styles.breadcrumbSeparator} aria-hidden="true">/</span>
      {isMultiInstance && !showParentOverview ? (
        <>
          <Link href={`/apps/${appKey}`} data-testid="breadcrumb-parent">
            {appKey}
          </Link>
          <span class={styles.breadcrumbSeparator} aria-hidden="true">/</span>
          <span class={styles.breadcrumbCurrent} aria-current="page">
            {instanceName}
          </span>
        </>
      ) : (
        <span class={styles.breadcrumbCurrent} aria-current="page">
          {appKey}
        </span>
      )}
    </nav>
  );
}
