/**
 * The app's base URL, read once from `document.baseURI`.
 *
 * The backend substitutes `index.html`'s `<base href>` per request, so behind Home Assistant ingress or a
 * sub-path reverse proxy it names the prefix the proxy stripped (e.g. `/api/hassio_ingress/<token>/`), and
 * `/` otherwise. Every URL the app builds goes through this module so it lands under that prefix; the
 * built bundle holds no absolute same-origin paths (enforced by the build plugin in `vite.config.ts`).
 */

const BASE = new URL(document.baseURI);

/** The base's path without its trailing `/` (empty at `/`): wouter's `<Router base>`. */
export const ROUTER_BASE = BASE.pathname.replace(/\/$/, "");

/** Resolve an app-relative path against the base. A leading `/` means the app root, not the origin root. */
export function resolveAppUrl(path: string): string {
  return new URL(path.replace(/^\//, ""), BASE).href;
}

/** The WebSocket URL for an app-relative path: the resolved URL with `http`→`ws` and `https`→`wss`. */
export function resolveWsUrl(path: string): string {
  return resolveAppUrl(path).replace(/^http/, "ws");
}
