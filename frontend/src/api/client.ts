/** Base API client for fetching JSON from the Hassette backend. */

const BASE_URL = "/api";
const JSON_CONTENT_TYPE = "application/json";

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly statusText: string,
    message?: string,
  ) {
    super(message ?? `API error: ${status} ${statusText}`);
    this.name = "ApiError";
  }
}

/** Extracts a human-readable error message from a non-ok response's JSON body, if present. */
async function extractErrorMessage(response: Response): Promise<string | undefined> {
  try {
    const body: Record<string, unknown> = await response.json();
    const raw = body.detail ?? body.message;
    return typeof raw === "string" ? raw : undefined;
  } catch {
    return undefined;
  }
}

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const url = `${BASE_URL}${path}`;
  const response = await fetch(url, {
    ...init,
    credentials: "same-origin",
    headers: {
      Accept: JSON_CONTENT_TYPE,
      ...init?.headers,
    },
  });

  if (!response.ok) {
    const detail = await extractErrorMessage(response);
    throw new ApiError(response.status, response.statusText, detail);
  }

  return response.json() as Promise<T>;
}

export function apiPost<T>(path: string, body?: unknown): Promise<T> {
  return apiFetch<T>(path, {
    method: "POST",
    headers: { "Content-Type": JSON_CONTENT_TYPE },
    body: body ? JSON.stringify(body) : undefined,
  });
}

export type PostSessionResult = { ok: true } | { ok: false; message: string };

/**
 * Exchange a bearer token for a session cookie via `POST /api/auth/session`.
 *
 * Deliberately bypasses `apiFetch`/`apiPost` — those throw `ApiError` on a non-ok response,
 * which would trip the global 401 handling in `query-client.ts`'s `QueryCache.onError` and
 * bounce the caller straight back to the login view with no error shown. Wrong-token rejection
 * is exactly the case this route's own caller (the login form) needs to render inline instead.
 */
export async function postSession(token: string): Promise<PostSessionResult> {
  let response: Response;
  try {
    response = await fetch(`${BASE_URL}/auth/session`, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": JSON_CONTENT_TYPE },
      body: JSON.stringify({ token }),
    });
  } catch {
    return { ok: false, message: "Could not reach the server. Check your connection and try again." };
  }

  if (response.ok) return { ok: true };

  const detail = await extractErrorMessage(response);
  const message = detail ?? `API error: ${response.status} ${response.statusText}`;
  return { ok: false, message };
}
