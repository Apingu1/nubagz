const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000/api'

export class ApiError extends Error { constructor(public status:number, message:string){super(message)} }

function authHeaders(options:RequestInit = {}){
  const token = localStorage.getItem('nubagz_token')
  const headers = new Headers(options.headers || {})
  if (!headers.has('Content-Type') && options.body) headers.set('Content-Type','application/json')
  if (token) headers.set('Authorization', `Bearer ${token}`)
  return headers
}

async function apiError(res:Response){
  let message = `Request failed (${res.status})`
  try { const data = await res.json(); message = data.detail || message } catch {}
  return new ApiError(res.status, message)
}

export async function api<T>(path:string, options:RequestInit = {}):Promise<T>{
  const res = await fetch(`${API_URL}${path}`, {...options, headers:authHeaders(options)})
  if (!res.ok) throw await apiError(res)
  if (res.status === 204) return undefined as T
  return res.json()
}

export async function apiDownload(path:string, fallbackFilename:string):Promise<string>{
  const res = await fetch(`${API_URL}${path}`, {headers:authHeaders()})
  if (!res.ok) throw await apiError(res)
  const disposition = res.headers.get('Content-Disposition') || ''
  const match = disposition.match(/filename="?([^";]+)"?/i)
  const filename = match?.[1] || fallbackFilename
  const blob = await res.blob()
  const href = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = href
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(href)
  return filename
}
