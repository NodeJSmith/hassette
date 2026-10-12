/** Base API client for fetching JSON from the Hassette backend. */

import { resolveAppUrl } from "../lib/base-path";
import { useAppStore } from "../state/store";
import { LOGIN_PATH } from "../utils/app-routes";
import type { components } from "./generated-types";

type ProblemCode = components["schemas"]["ProblemCode"];
type ProblemDetail = components["schemas"]["ProblemDetail"];

/**
 * A non-ok response's parsed JSON, unvalidated. Keyed by the generated `ProblemDetail` members, so a rename
 * of one on the backend fails tsc here; `message` covers bodies that aren't problem details.
 */
type RawErrorBody = { [K in keyof ProblemDetail]?: unknown } & { message?: unknown };

/** App-relative, so requests resolve under the `<base href>` (see `lib/base-path.ts`). */
export const BASE_URL = "api";
const JSON_CONTENT_TYPE = "application/json";
const FETCH_CREDENTIALS: RequestCredentials = "same-origin";

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly statusText: string,
    message?: string,
    /**
     * The problem body's `code`, when the response carried one. A `string`, not `ProblemCode`: a newer
     * backend may send a code this build's generated union doesn't list.
     */
    public readonly code?: string,
  ) {
    super(message ?? formatApiError(status, statusText));
    this.name = "ApiError";
  }
}

/** Builds the generic `API error: <status> <statusText>` message used when no specific detail is available. */
function formatApiError(status: number, statusText: string): string {
  return `API error: ${status} ${statusText}`;
}

const UNAUTHORIZED = 401;
const NOT_AUTHENTICATED: ProblemCode = "not_authenticated";

/** What a 401 asks the UI to do. */
export type UnauthorizedOutcome = "login" | "session-expired";

/**
 * How to respond to `error` if it's a 401, or `null` if it isn't one.
 *
 * Hassette's own 401 (`not_authenticated`) means logging in helps. Any other 401 comes from something in
 * front of Hassette (Home Assistant's Supervisor answers one when an ingress session expires), where the
 * login form's request would get the same 401, so the UI shows a reload prompt instead.
 */
export function unauthorizedOutcome(error: unknown): UnauthorizedOutcome | null {
  if (!(error instanceof ApiError) || error.status !== UNAUTHORIZED) return null;
  return error.code === NOT_AUTHENTICATED ? "login" : "session-expired";
}

/**
 * Acts on a 401 by sending the operator to login or showing the session-expired view; a no-op for
 * anything else. Called from the QueryCache's `onError` and from `apiPost`, which together cover every
 * REST call; `apiFetch` itself stays side-effect-free.
 *
 * Idempotent, so it may fire twice for one failure (e.g. a query whose fetcher calls `apiPost`). The
 * WebSocket path maps the same outcomes in `hooks/use-websocket.ts`, using SPA navigation instead of a
 * full page load.
 */
export function handleUnauthorized(error: unknown): void {
  const outcome = unauthorizedOutcome(error);
  if (outcome === "login") window.location.assign(resolveAppUrl(LOGIN_PATH));
  if (outcome === "session-expired") useAppStore.getState().setSessionExpired();
}

interface ErrorBody {
  message?: string;
  code?: string;
}

/** Extracts a human-readable message and problem code from a non-ok response's JSON body, if present. */
async function extractErrorBody(response: Response): Promise<ErrorBody> {
  try {
    const body: RawErrorBody = await response.json();
    const raw = body.detail ?? body.message;
    return {
      message: typeof raw === "string" ? raw : undefined,
      code: typeof body.code === "string" ? body.code : undefined,
    };
  } catch {
    return {};
  }
}

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(resolveAppUrl(`${BASE_URL}${path}`), {
    ...init,
    credentials: FETCH_CREDENTIALS,
    headers: {
      Accept: JSON_CONTENT_TYPE,
      ...init?.headers,
    },
  });

  if (!response.ok) {
    const { message, code } = await extractErrorBody(response);
    throw new ApiError(response.status, response.statusText, message, code);
  }

  return response.json() as Promise<T>;
}

/**
 * POSTs JSON and routes a 401 through `handleUnauthorized` before rethrowing, because action calls
 * (buttons, palette) don't go through a query and so never reach the QueryCache's handler.
 */
export async function apiPost<T>(path: string, body?: unknown): Promise<T> {
  try {
    return await apiFetch<T>(path, {
      method: "POST",
      headers: { "Content-Type": JSON_CONTENT_TYPE },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch (error) {
    handleUnauthorized(error);
    throw error;
  }
}

export type PostSessionResult = { ok: true } | { ok: false; message: string };

/**
 * Exchange a bearer token for a session cookie via `POST /api/auth/session`.
 *
 * Deliberately bypasses `apiPost`: it runs `handleUnauthorized`, which would bounce a wrong-token
 * login straight back to the login view with no error shown. Wrong-token rejection is exactly the
 * case the login form needs to render inline. (`apiFetch` has no such side effect, but it throws
 * `ApiError` on a non-ok response, which this function maps to a result instead.)
 */
export async function postSession(token: string): Promise<PostSessionResult> {
  let response: Response;
  try {
    response = await fetch(resolveAppUrl(`${BASE_URL}/auth/session`), {
      method: "POST",
      credentials: FETCH_CREDENTIALS,
      headers: { "Content-Type": JSON_CONTENT_TYPE },
      body: JSON.stringify({ token }),
    });
  } catch {
    return { ok: false, message: "Could not reach the server. Check your connection and try again." };
  }

  if (response.ok) return { ok: true };

  const { message } = await extractErrorBody(response);
  return { ok: false, message: message ?? formatApiError(response.status, response.statusText) };
}
