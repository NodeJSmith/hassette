import type * as React from "react";

/**
 * Click handler for an in-page `#id` anchor: focus (and scroll to) the target without navigating. Under the
 * backend's `<base href>`, a bare `#id` href resolves against the base, not the current route, so following
 * it would leave the page. Every in-page anchor uses this (enforced by a `no-restricted-syntax` rule in
 * `eslint.config.js`).
 */
export function focusInPageTarget(id: string): (e: React.MouseEvent<HTMLAnchorElement>) => void {
  return (e) => {
    e.preventDefault();
    const target = document.getElementById(id);
    target?.focus();
    target?.scrollIntoView();
  };
}
