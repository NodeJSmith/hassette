import clsx from "clsx";

import { useLocation } from "wouter";
import styles from "../../pages/app-detail.module.css";

interface Props {
  appKey: string;
  isMultiInstance: boolean;
  showParentOverview: boolean;
  instanceName: string;
}

export function AppDetailBreadcrumb({ appKey, isMultiInstance, showParentOverview, instanceName }: Props) {
  const [, navigate] = useLocation();

  return (
    <nav class={clsx(styles.breadcrumb, "ht-mb-3")} aria-label="Breadcrumb">
      <a href="/apps">apps</a>
      <span class={styles.breadcrumbSeparator} aria-hidden="true">/</span>
      {isMultiInstance && !showParentOverview ? (
        <>
          <a
            href={`/apps/${appKey}`}
            data-testid="breadcrumb-parent"
            onClick={(e) => {
              e.preventDefault();
              navigate(`/apps/${appKey}`);
            }}
          >
            {appKey}
          </a>
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
