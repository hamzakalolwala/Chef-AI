import { useCallback, useEffect, useRef, useState } from 'react'
import { wsUrl } from './api'
import type { Dish, KitchenEvent, KitchenState, Pantry, ServerInfo } from './types'

type Listener = (e: KitchenEvent) => void

/** Live connection to the backend's /ws/dashboard socket, with auto-reconnect. */
export function useKitchen() {
  const [state, setState] = useState<KitchenState | null>(null)
  const [events, setEvents] = useState<KitchenEvent[]>([])
  const [dishes, setDishes] = useState<Dish[]>([])
  const [info, setInfo] = useState<ServerInfo | null>(null)
  const [pantry, setPantry] = useState<Pantry | null>(null)
  const [connected, setConnected] = useState(false)
  const listeners = useRef(new Set<Listener>())

  useEffect(() => {
    let ws: WebSocket | null = null
    let retry: ReturnType<typeof setTimeout> | undefined
    let ping: ReturnType<typeof setInterval> | undefined
    let closed = false

    const connect = () => {
      ws = new WebSocket(wsUrl('/ws/dashboard'))
      ws.onopen = () => {
        setConnected(true)
        ping = setInterval(() => ws?.readyState === WebSocket.OPEN && ws.send('ping'), 20000)
      }
      ws.onmessage = (m) => {
        const msg = JSON.parse(m.data)
        switch (msg.type) {
          case 'hello':
            setInfo(msg.info)
            setDishes(msg.dishes)
            setPantry(msg.pantry)
            setEvents(msg.events)
            setState(msg.state)
            break
          case 'state':
            setState(msg)
            break
          case 'info':
            setInfo(msg.info)
            break
          case 'event':
            setEvents((prev) => [...prev.slice(-119), msg.event])
            listeners.current.forEach((fn) => fn(msg.event))
            break
        }
      }
      ws.onclose = () => {
        setConnected(false)
        clearInterval(ping)
        if (!closed) retry = setTimeout(connect, 1500)
      }
    }
    connect()
    return () => {
      closed = true
      clearTimeout(retry)
      clearInterval(ping)
      ws?.close()
    }
  }, [])

  const onEvent = useCallback((fn: Listener) => {
    listeners.current.add(fn)
    return () => {
      listeners.current.delete(fn)
    }
  }, [])

  return { state, events, dishes, info, connected, onEvent, pantry, setPantry }
}
