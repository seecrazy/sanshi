// WebSocket 客户端：首消息鉴权（token 不进 URL）+ 25s 心跳 + 自动重连
import { API_BASE, token } from './api'

type Handler = (event: any) => void

const handlers = new Map<string, Set<Handler>>()
let ws: WebSocket | null = null
let heartbeat: number | null = null
let reconnectTimer: number | null = null
let started = false

export function onWsEvent(type: string, handler: Handler) {
  if (!handlers.has(type)) handlers.set(type, new Set())
  handlers.get(type)!.add(handler)
  return () => handlers.get(type)?.delete(handler)
}

function dispatch(event: any) {
  if (event && event.type) handlers.get(event.type)?.forEach((h) => h(event))
  handlers.get('*')?.forEach((h) => h(event))
}

function wsUrl(): string {
  return API_BASE.replace(/^http/, 'ws') + '/ws'
}

function connect() {
  const t = token()
  if (!t) return
  ws = new WebSocket(wsUrl())
  ws.onopen = () => {
    ws!.send(JSON.stringify({ type: 'auth', token: t }))
    if (heartbeat) window.clearInterval(heartbeat)
    heartbeat = window.setInterval(() => {
      if (ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'ping' }))
    }, 25000)
  }
  ws.onmessage = (e) => {
    try {
      dispatch(JSON.parse(e.data))
    } catch {
      /* 忽略非 JSON 帧 */
    }
  }
  ws.onclose = () => {
    if (heartbeat) window.clearInterval(heartbeat)
    if (started) {
      reconnectTimer = window.setTimeout(connect, 3000)
    }
  }
}

export function startWs() {
  started = true
  connect()
}

export function stopWs() {
  started = false
  if (reconnectTimer) window.clearTimeout(reconnectTimer)
  ws?.close()
  ws = null
}
