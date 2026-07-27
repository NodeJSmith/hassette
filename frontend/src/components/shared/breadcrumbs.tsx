import { Link } from "wouter";

import styles from "./breadcrumbs.module.css";

export interface Crumb {
  label: string;
  /** Omit on the final crumb — the page you are already on. */
  href?: string;
}

interface Props {
  items: Crumb[];
  "data-testid"?: string;
}

/**
 * Ancestor trail. Linked crumbs carry the accent so the path reads as navigation.
 *
 * Below 768px all but the last two crumbs are visually clipped by CSS and an ellipsis
 * stands in for them, so a deep trail cannot crowd the hamburger and time selector out of
 * the status bar. They are clipped rather than removed, so screen readers still get the
 * whole path at every width and no layout-dependent state has to be tracked in JS.
 */
export function Breadcrumbs({ items, "data-testid": testId = "breadcrumbs" }: Props) {
  if (items.length === 0) return null;

  return (
    <nav className={styles.nav} aria-label="Breadcrumb" data-testid={testId}>
      <ol className={styles.list}>
        {items.length > 2 && (
          <li className={styles.ellipsis} aria-hidden="true">
            …
          </li>
        )}
        {items.map((crumb, i) => (
          <li key={`${crumb.label}-${i}`} className={styles.item}>
            {i > 0 && (
              <span className={styles.separator} aria-hidden="true">
                /
              </span>
            )}
            {crumb.href ? (
              <Link href={crumb.href} className={styles.link}>
                {crumb.label}
              </Link>
            ) : (
              <span className={styles.current} aria-current="page">
                {crumb.label}
              </span>
            )}
          </li>
        ))}
      </ol>
    </nav>
  );
}
