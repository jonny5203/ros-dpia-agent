/**
 * Credentialed fetch wrapper (BFF pattern): the SPA holds no tokens; the
 * httpOnly session cookie travels with every request. Errors arrive as
 * RFC 9457 `application/problem+json` (see backend app/core/exceptions.py).
 */

const BASE = import.meta.env.VITE_API_BASE ?? "";

export interface Problem {
  type: string;
  title: string;
  status: number;
  detail: string;
  errors?: unknown;
}

export class ApiError extends Error {
  status: number;
  problem: Problem;
  constructor(status: number, problem: Problem) {
    super(problem.detail || problem.title || `Request failed (${status})`);
    this.status = status;
    this.problem = problem;
  }
}

// Routes that must not bounce on 401: the auth pages themselves handle the
// unauthenticated state, so a redirect here would loop (e.g. /login → 401 → /login).
const AUTH_ROUTES = ["/login", "/callback"];

function redirectToLogin(): void {
  const path = window.location.pathname;
  if (AUTH_ROUTES.some((r) => path.startsWith(r))) return;
  // Preserve where the user was headed so /callback can return there.
  const ret = encodeURIComponent(path + window.location.search);
  window.location.assign(`/login?ret=${ret}`);
}

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    credentials: "include",
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });

  if (res.status === 401) {
    redirectToLogin();
    // Throw so the caller (loader / query) stops; the navigation is already
    // underway and the current render path will be discarded by the browser.
    throw new ApiError(401, {
      type: "about:blank",
      title: "Unauthorized",
      status: 401,
      detail: "Session expired — redirecting to login.",
    });
  }

  const contentType = res.headers.get("content-type") ?? "";
  const body = contentType.includes("json") ? await res.json() : null;

  if (!res.ok) {
    throw new ApiError(
      res.status,
      (body as Problem) ?? {
        type: "about:blank",
        title: "Request failed",
        status: res.status,
        detail: `HTTP ${res.status}`,
      },
    );
  }
  return body as T;
}

export interface HealthResponse {
  status: string;
  app: string;
  version: string;
  openrouter_ms: number;
  openrouter: {
    base_url: string;
    key_configured: boolean;
    reachable: boolean;
    key_valid: boolean | null;
  };
}

export const getHealth = () => apiFetch<HealthResponse>("/api/health");
