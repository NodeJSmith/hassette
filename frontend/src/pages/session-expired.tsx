import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";

import { useDocumentTitle } from "../hooks/use-document-title";
import { FULL_PAGE_CLASS, FULL_PAGE_TITLE_CLASS } from "./full-page-card";

const CARD_CLASS = "flex w-full max-w-sm flex-col gap-4 p-6";

/**
 * Reload the top-level page, so Home Assistant starts a fresh ingress session before re-embedding the UI.
 * Reloading only this frame would hit the same expired session. Falls back to this window when the top
 * frame is cross-origin (or there is none).
 */
function reloadTop(): void {
  try {
    (window.top ?? window).location.reload();
  } catch {
    window.location.reload();
  }
}

/**
 * Shown in place of the app after a 401 that isn't Hassette's own, such as Supervisor's when a Home
 * Assistant ingress session expires. Hassette's login form can't help there: its request would get the
 * same 401.
 */
export function SessionExpiredPage() {
  useDocumentTitle("Session expired");
  return (
    <div className={FULL_PAGE_CLASS} data-testid="session-expired-page">
      <Card className={CARD_CLASS}>
        <h1 className={FULL_PAGE_TITLE_CLASS}>session expired</h1>
        <p className="text-sm text-foreground-secondary">
          The session this page was opened with is no longer valid. Reload Home Assistant (or the page that links here)
          to start a new one.
        </p>
        <Button onClick={reloadTop}>Reload</Button>
      </Card>
    </div>
  );
}
