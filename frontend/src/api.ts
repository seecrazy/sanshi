// API 封装：所有请求经此，401 自动登出
export const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000'

let onUnauthorized: (() => void) | null = null
export function setUnauthorizedHandler(fn: () => void) {
  onUnauthorized = fn
}

export function token(): string | null {
  return localStorage.getItem('sanshi_token')
}

async function request(method: string, path: string, body?: any): Promise<any> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  const t = token()
  if (t) headers['Authorization'] = `Bearer ${t}`
  const res = await fetch(`${API_BASE}${path}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (res.status === 401) {
    onUnauthorized?.()
    throw new Error('未登录或登录已过期')
  }
  const data = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(data.detail || `请求失败(${res.status})`)
  return data
}

export const api = {
  get: (p: string) => request('GET', p),
  post: (p: string, b?: any) => request('POST', p, b ?? {}),
  put: (p: string, b?: any) => request('PUT', p, b ?? {}),
  del: (p: string) => request('DELETE', p),
}

export const yuan = (cents: number) => `¥${(cents / 100).toFixed(2)}`

export const STATUS_LABEL: Record<string, string> = {
  PENDING_PAYMENT: '待支付', PAID: '已支付', PENDING_ACCEPT: '待商家接单', ACCEPTED: '商家已接单',
  ASSIGNED: '骑手已接单', PICKED: '配送中', DELIVERED: '已送达', COMPLETED: '已完成',
  CANCELLED: '已取消', REFUNDED: '已退款', DISPUTED: '争议处理中',
}
