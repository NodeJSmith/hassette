import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";

import { useDocumentTitle } from "../hooks/use-document-title";
import { resolveAppUrl, ROUTER_BASE } from "../lib/base-path";
import { LOGIN_PATH } from "../utils/app-routes";
import { FULL_PAGE_CLASS, FULL_PAGE_TITLE_CLASS } from "./full-page-card";

const CARD_CLASS = "flex w-full max-w-sm flex-col gap-4 p-6";
/** Served at the origin root, where a 401 can be Hassette's own and its login form can work. */
const AT_ROOT_BASE = ROUTER_BASE === "";

/**
 * Reload the top-level page, so whatever embeds or fronts the UI (Home Assistant's ingress page, a proxy's
 * login) starts a fresh session. Reloading only this frame would hit the same expired session. Falls back
 * to this window when the top frame is cross-origin (or there is none).
 */
export function reloadTop(): void {
  try {
    (window.top ?? window).location.reload();
  } catch {
    window.location.reload();
  }
}

interface SessionExpiredPageProps {
  /**
   * Also offer Hassette's own login. Only at root base: there the 401 may be Hassette's with a body a proxy
   * mangled, and the login form can work. Under a prefix, the proxy's session gates the login request too.
   */
  offerLogin?: boolean;
}

/**
 * Shown in place of the app after a 401 that isn't Hassette's own, such as Supervisor's when a Home
 * Assistant ingress session expires, or a forward-auth proxy's. Hassette's login form can't help there:
 * its request would get the same 401.
 */
export function SessionExpiredPage({ offerLogin = AT_ROOT_BASE }: SessionExpiredPageProps) {
  useDocumentTitle("Session expired");
  return (
    <div className={FULL_PAGE_CLASS} data-testid="session-expired-page">
      <Card className={CARD_CLASS}>
        <h1 className={FULL_PAGE_TITLE_CLASS}>session expired</h1>
        <p className="text-sm text-foreground-secondary">
          The session this page was opened with is no longer valid. Reload to start a new one from the page that opened
          Hassette, such as Home Assistant or your proxy's sign-in.
        </p>
        <Button onClick={reloadTop}>Reload</Button>
        {offerLogin && (
          <Button variant="ghost" onClick={() => window.location.assign(resolveAppUrl(LOGIN_PATH))}>
            Log in to Hassette
          </Button>
        )}
      </Card>
    </div>
  );
}
