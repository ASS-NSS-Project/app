import axios from 'axios'
import type { AxiosInstance } from 'axios'

// Lazily import the auth store to avoid circular dependency at module load time
function getToken(): string | null {
  return localStorage.getItem('rag_token')
}

const http: AxiosInstance = axios.create({
  baseURL: '/',
})

http.interceptors.request.use((config) => {
  const token = getToken()
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

http.interceptors.response.use(
  (response) => response,
  (error) => {
    // Redirect to login on 401
    if (error.response?.status === 401) {
      localStorage.removeItem('rag_token')
      localStorage.removeItem('rag_user')
      window.location.hash = '#/login'
    }
    return Promise.reject(error)
  }
)

export async function get<T>(path: string, params?: Record<string, unknown>): Promise<T> {
  const res = await http.get<T>(path, { params })
  return res.data
}

export async function post<T>(path: string, body?: unknown): Promise<T> {
  const res = await http.post<T>(path, body)
  return res.data
}

export async function patch<T>(path: string, body?: unknown): Promise<T> {
  const res = await http.patch<T>(path, body)
  return res.data
}

export async function del<T>(path: string): Promise<T> {
  const res = await http.delete<T>(path)
  return res.data
}

// Login uses application/x-www-form-urlencoded (OAuth2PasswordRequestForm)
export async function loginForm(username: string, password: string) {
  const body = new URLSearchParams({ username, password })
  const res = await axios.post('/auth/login', body)
  return res.data
}
