import { Link } from "wouter";

import { cn } from "@/lib/utils";

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
 * Below the sidebar breakpoint all but the last two crumbs are visually clipped by CSS and an ellipsis
 * stands in for them, so a deep trail cannot crowd the hamburger and time selector out of
 * the status bar. They are clipped rather than removed, so screen readers still get the
 * whole path at every width and no layout-dependent state has to be tracked in JS.
 */
export function Breadcrumbs({ items, "data-testid": testId = "breadcrumbs" }: Props) {
  if (items.length === 0) return null;

  return (
    <nav className="min-w-0 overflow-hidden" aria-label="Breadcrumb" data-testid={testId}>
      <ol className="m-0 flex list-none items-center gap-1 p-0 font-sans text-sm">
        {items.length > 2 && (
          <li
            className="hidden text-foreground-faint max-sidebar:inline-flex max-sidebar:items-center"
            aria-hidden="true"
          >
            …
          </li>
        )}
        {items.map((crumb, i) => (
          <li
            key={`${crumb.label}-${i}`}
            className={cn(
              "inline-flex min-w-0 items-center gap-1",
              "max-sidebar:[&:not(:nth-last-child(-n+2))]:sr-only",
              "max-sidebar:[&:nth-last-child(2)>span]:hidden",
            )}
          >
            {i > 0 && (
              <span className="text-foreground-faint" aria-hidden="true">
                /
              </span>
            )}
            {crumb.href ? (
              <Link
                href={crumb.href}
                className="block min-w-0 truncate text-primary no-underline hover:text-[var(--primary-hover)] hover:underline"
              >
                {crumb.label}
              </Link>
            ) : (
              <span className="truncate font-medium text-foreground" aria-current="page">
                {crumb.label}
              </span>
            )}
          </li>
        ))}
      </ol>
    </nav>
  );
}
