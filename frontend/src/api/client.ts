function getToken(): string | null {
  return localStorage.getItem('rag_token')
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

  const res = await fetch(path, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })

  if (res.status === 401) {
    localStorage.removeItem('rag_token')
    localStorage.removeItem('rag_user')
    window.location.hash = '#/login'
    throw new Error('Unauthorized')
  }

  if (!res.ok) {
    const data = await res.json().catch(() => ({}))
    throw Object.assign(
      new Error((data as { detail?: string })?.detail ?? `HTTP ${res.status}`),
      { response: { data } },
    )
  }

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
