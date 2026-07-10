/** Base API client for fetching JSON from the Hassette backend. */

const BASE_URL = "/api";

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

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const url = `${BASE_URL}${path}`;
  const response = await fetch(url, {
    ...init,
    headers: {
      Accept: "application/json",
      ...init?.headers,
    },
  });

  if (!response.ok) {
    let detail: string | undefined;
    try {
      const body: Record<string, unknown> = await response.json();
      const raw = body.detail ?? body.message;
      detail = typeof raw === "string" ? raw : undefined;
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(response.status, response.statusText, detail);
  }

  return response.json() as Promise<T>;
}

function apiWrite<T>(method: "POST" | "PUT", path: string, body?: unknown): Promise<T> {
  return apiFetch<T>(path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
}

export const apiPost = <T>(path: string, body?: unknown) => apiWrite<T>("POST", path, body);
export const apiPut = <T>(path: string, body?: unknown) => apiWrite<T>("PUT", path, body);
