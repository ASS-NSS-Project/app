function getToken(): string | null {
  return sessionStorage.getItem('rag_token') ?? localStorage.getItem('rag_token')
}

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

async function request<T>(
  method: string,
  path: string,
  body?: unknown,
): Promise<T> {
  const headers: Record<string, string> = {}
  const token = getToken()
  if (token) headers['Authorization'] = `Bearer ${token}`
  if (body !== undefined) headers['Content-Type'] = 'application/json'

  let res: Response
  try {
    res = await fetch(path, {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    })
  } catch (networkErr) {
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
    localStorage.removeItem('rag_token')
    localStorage.removeItem('rag_user')
    sessionStorage.removeItem('rag_token')
    sessionStorage.removeItem('rag_user')
    window.dispatchEvent(new CustomEvent('auth:expired'))
    logError(method, path, 401, 'Unauthorized — session expired')
    throw new Error('Unauthorized')
  }

  if (!res.ok) {
    const data = await res.json().catch(() => ({}))
    const detail = (data as { detail?: string })?.detail ?? `HTTP ${res.status}`
    logError(method, path, res.status, detail)
    throw Object.assign(new Error(detail), { response: { data } })
  }

  if (res.status === 204) return undefined as T
  return res.json() as Promise<T>
}

export function get<T>(path: string): Promise<T> {
  return request<T>('GET', path)
}

export function post<T>(path: string, body?: unknown): Promise<T> {
  return request<T>('POST', path, body)
}

export function patch<T>(path: string, body?: unknown): Promise<T> {
  return request<T>('PATCH', path, body)
}

export function del<T>(path: string): Promise<T> {
  return request<T>('DELETE', path)
}

// Login uses application/x-www-form-urlencoded (OAuth2PasswordRequestForm)
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
