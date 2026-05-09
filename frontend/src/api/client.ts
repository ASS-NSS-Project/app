/**
 * api/client.ts — Minimal HTTP client built on the native Fetch API
 *
 * Provides four thin wrappers (get, post, patch, del) and a special loginForm
 * function for the OAuth2 password form endpoint. All functions:
 * - Attach the Bearer token from storage to every request.
 * - Parse the JSON response and return it typed as <T>.
 * - Emit structured JSON error logs to the browser console (matching the
 *   backend's python-json-logger format so Loki rules can pick them up too).
 * - Dispatch a custom "auth:expired" event on HTTP 401 so App.vue can redirect
 *   to /login without coupling the API layer to the router.
 *
 * This module is intentionally dependency-free — no Axios, no custom class —
 * because the Fetch API is sufficient for the application's needs and avoids
 * adding a runtime bundle dependency.
 */

/**
 * Read the JWT (or opaque API token) from whichever storage was used at login.
 * sessionStorage takes priority for local first-admin sessions.
 * Falls back to localStorage for OAuth callbacks.
 */
function getToken(): string | null {
  return sessionStorage.getItem('webrag_token') ?? localStorage.getItem('webrag_token')
}

/**
 * Emit a structured JSON error to the browser console.
 * The same JSON format as the backend python-json-logger output so frontend
 * errors can be correlated with backend errors in Loki/Grafana.
 */
function logError(method: string, path: string, status: number, detail: string, extra?: object) {
  console.error(JSON.stringify({
    timestamp: new Date().toISOString(),
    level: 'ERROR',
    service: 'frontend',
    event: 'api_error',
    method,
    path,
    status,
    detail,
    ...extra,
  }))
}

/**
 * Core request helper — all public exports delegate here.
 *
 * @param method - HTTP verb ("GET", "POST", "PATCH", "DELETE")
 * @param path   - API path relative to origin (e.g. "/auth/me")
 * @param body   - Optional request body, serialised to JSON
 * @returns      - Parsed response body typed as T
 * @throws       - Error with a human-readable message and optional .response.data
 */
async function request<T>(
  method: string,
  path: string,
  body?: unknown,
): Promise<T> {
  const headers: Record<string, string> = {}
  const token = getToken()
  if (token) headers['Authorization'] = `Bearer ${token}`
  // Only set Content-Type when we are actually sending a body — some endpoints
  // (e.g. DELETE) have no body and adding the header breaks them on some backends.
  if (body !== undefined) headers['Content-Type'] = 'application/json'

  let res: Response
  try {
    res = await fetch(path, {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    })
  } catch (networkErr) {
    // Network-level failure (no internet, DNS error, CORS preflight blocked, etc.)
    console.error(JSON.stringify({
      timestamp: new Date().toISOString(),
      level: 'ERROR',
      service: 'frontend',
      event: 'network_error',
      method,
      path,
      error: String(networkErr),
    }))
    throw networkErr
  }

  if (res.status === 401) {
    // Token expired or revoked — clear all auth storage and notify App.vue.
    // App.vue listens for "auth:expired" and redirects to /login.
    localStorage.removeItem('webrag_token')
    localStorage.removeItem('webrag_user')
    sessionStorage.removeItem('webrag_token')
    sessionStorage.removeItem('webrag_user')
    // CustomEvent allows multiple components to listen without coupling them to each other.
    window.dispatchEvent(new CustomEvent('auth:expired'))
    logError(method, path, 401, 'Unauthorized — session expired')
    throw new Error('Unauthorized')
  }

  if (!res.ok) {
    // Parse the FastAPI error body { detail: "..." } if possible.
    const data = await res.json().catch(() => ({}))
    const detail = (data as { detail?: string })?.detail ?? `HTTP ${res.status}`
    logError(method, path, res.status, detail)
    // Attach the raw response data so callers can inspect it if needed.
    throw Object.assign(new Error(detail), { response: { data } })
  }

  // HTTP 204 No Content — successful but no response body (e.g. DELETE).
  if (res.status === 204) return undefined as T
  return res.json() as Promise<T>
}

/** HTTP GET — fetch data without a request body. */
export function get<T>(path: string): Promise<T> {
  return request<T>('GET', path)
}

/** HTTP POST — create a resource or trigger an action. */
export function post<T>(path: string, body?: unknown): Promise<T> {
  return request<T>('POST', path, body)
}

/** HTTP PATCH — partially update an existing resource. */
export function patch<T>(path: string, body?: unknown): Promise<T> {
  return request<T>('PATCH', path, body)
}

/** HTTP DELETE — remove a resource. Returns void for 204 responses. */
export function del<T>(path: string): Promise<T> {
  return request<T>('DELETE', path)
}

/**
 * Log in with username + password using OAuth2PasswordRequestForm encoding.
 *
 * The /auth/login endpoint follows the OAuth2 standard and requires
 * application/x-www-form-urlencoded — NOT application/json. URLSearchParams
 * produces that encoding when passed as the fetch body.
 *
 * The regular request() helper cannot be used here because it always sets
 * Content-Type to application/json when a body is provided.
 */
export async function loginForm(username: string, password: string) {
  const body = new URLSearchParams({ username, password })
  const res = await fetch('/auth/login', { method: 'POST', body })
  if (!res.ok) {
    const data = await res.json().catch(() => ({}))
    throw Object.assign(
      new Error((data as { detail?: string })?.detail ?? 'Login failed'),
      { response: { data } },
    )
  }
  return res.json()
}
