const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000/api'

export class ApiError extends Error { constructor(public status:number, message:string){super(message)} }

export async function api<T>(path:string, options:RequestInit = {}):Promise<T>{
  const token = localStorage.getItem('nubagz_token')
  const headers = new Headers(options.headers || {})
  if (!headers.has('Content-Type') && options.body) headers.set('Content-Type','application/json')
  if (token) headers.set('Authorization', `Bearer ${token}`)
  const res = await fetch(`${API_URL}${path}`, {...options, headers})
  if (!res.ok){
    let message = `Request failed (${res.status})`
    try { const data = await res.json(); message = data.detail || message } catch {}
    throw new ApiError(res.status, message)
  }
  if (res.status === 204) return undefined as T
  return res.json()
}
