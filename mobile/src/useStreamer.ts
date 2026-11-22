import * as Battery from 'expo-battery'
import type { CameraView } from 'expo-camera'
import * as Haptics from 'expo-haptics'
import { type RefObject, useCallback, useEffect, useRef, useState } from 'react'

export type Zone = { x: number; y: number; w: number; h: number }
export type BurnerSummary = {
  id: string
  name: string
  status: string
  flame: boolean
  zone: Zone
  dish: string | null
  seconds: number
  progress: number | null
}
export type ServerEvent = { id: number; level: 'info' | 'warn' | 'danger' | 'success'; message: string }
export type Conn = 'idle' | 'connecting' | 'open' | 'closed'
export type ProfileLite = { id: string; name: string; emoji: string }
export type Command = { cmd: 'pause' | 'resume' | 'fps' | 'torch' | 'buzz'; value?: number | boolean }

/**
 * Captures a still from the camera every 1/fps seconds and pushes it to the Tadka backend as
 * JSON {type:"frame", jpeg:<base64>} over a WebSocket. Cooking changes slowly, so 1-3 fps of
 * small JPEGs is plenty and keeps the phone cool. Reconnects automatically.
 */
export function useStreamer(
  url: string,
  camera: RefObject<CameraView | null>,
  opts: { fps: number; running: boolean; ready: boolean; torch?: boolean; onCommand?: (c: Command) => void },
) {
  const [conn, setConn] = useState<Conn>('idle')
  const [burners, setBurners] = useState<BurnerSummary[]>([])
  const [serverFps, setServerFps] = useState(0)
  const [sentFps, setSentFps] = useState(0)
  const [lastEvent, setLastEvent] = useState<ServerEvent | null>(null)
  const [profile, setProfile] = useState<ProfileLite | null>(null)
  const [profiles, setProfiles] = useState<ProfileLite[]>([])
  const [fogged, setFogged] = useState(false)
  const ws = useRef<WebSocket | null>(null)
  const optsRef = useRef(opts)
  optsRef.current = opts
  const lastEventId = useRef<number | null>(null)

  // --- socket lifecycle -------------------------------------------------------------------
  useEffect(() => {
    // The socket stays open while paused, so the dashboard can still resume / control the phone.
    if (!url) return
    let closed = false
    let retry: ReturnType<typeof setTimeout> | undefined
    const connect = () => {
      setConn('connecting')
      const sock = new WebSocket(url)
      ws.current = sock
      sock.onopen = () => {
        setConn('open')
        sock.send(JSON.stringify({ type: 'hello', device: 'Tadka Cam' }))
      }
      sock.onmessage = (m) => {
        try {
          const msg = JSON.parse(String(m.data))
          if (msg.type === 'command') {
            optsRef.current.onCommand?.({ cmd: msg.cmd, value: msg.value })
            return
          }
          if (msg.type === 'summary') {
            setBurners(msg.burners)
            setServerFps(msg.fps)
            if (msg.profile) setProfile(msg.profile)
            if (msg.profiles) setProfiles(msg.profiles)
            setFogged(!!msg.fogged)
            const ev: ServerEvent | null = msg.last_event
            if (ev && ev.id !== lastEventId.current) {
              if (lastEventId.current !== null && ev.level !== 'info') {
                Haptics.notificationAsync(
                  ev.level === 'danger'
                    ? Haptics.NotificationFeedbackType.Error
                    : ev.level === 'warn'
                      ? Haptics.NotificationFeedbackType.Warning
                      : Haptics.NotificationFeedbackType.Success,
                )
              }
              lastEventId.current = ev.id
              setLastEvent(ev)
            }
          }
        } catch {
          /* ignore malformed messages */
        }
      }
      sock.onerror = () => {}
      sock.onclose = () => {
        if (ws.current === sock) ws.current = null
        setConn('closed')
        if (!closed) retry = setTimeout(connect, 2000)
      }
    }
    connect()
    return () => {
      closed = true
      clearTimeout(retry)
      ws.current?.close()
      ws.current = null
      setConn('idle')
    }
  }, [url])

  // --- status for the dashboard (battery matters for an old phone left by the stove) -------
  useEffect(() => {
    const send = async () => {
      const sock = ws.current
      if (!sock || sock.readyState !== WebSocket.OPEN) return
      let battery: number | null = null
      let charging: boolean | null = null
      try {
        battery = Math.round((await Battery.getBatteryLevelAsync()) * 100)
        const st = await Battery.getBatteryStateAsync()
        charging = st === Battery.BatteryState.CHARGING || st === Battery.BatteryState.FULL
      } catch {
        /* simulator / unsupported */
      }
      const o = optsRef.current
      sock.send(JSON.stringify({ type: 'status', battery, charging, paused: !o.running, fps: o.fps, torch: !!o.torch }))
    }
    const t = setInterval(send, 10000)
    const first = setTimeout(send, 1500)
    return () => {
      clearInterval(t)
      clearTimeout(first)
    }
  }, [url, conn, opts.running, opts.fps, opts.torch])

  // --- capture loop -----------------------------------------------------------------------
  useEffect(() => {
    if (!opts.running) return
    let alive = true
    let sent = 0
    const meter = setInterval(() => {
      setSentFps(sent / 2)
      sent = 0
    }, 2000)
    ;(async () => {
      while (alive) {
        const t0 = Date.now()
        const sock = ws.current
        const cam = camera.current
        // Skip a frame if the network is backed up rather than queueing stale images.
        if (sock && sock.readyState === WebSocket.OPEN && cam && optsRef.current.ready && sock.bufferedAmount < 400_000) {
          try {
            const pic = await cam.takePictureAsync({ quality: 0.35, base64: true, shutterSound: false })
            if (pic?.base64 && alive && sock.readyState === WebSocket.OPEN) {
              sock.send(JSON.stringify({ type: 'frame', jpeg: pic.base64 }))
              sent++
            }
          } catch {
            /* camera busy / backgrounded: try again next tick */
          }
        }
        const wait = Math.max(50, 1000 / optsRef.current.fps - (Date.now() - t0))
        await new Promise((r) => setTimeout(r, wait))
      }
    })()
    return () => {
      alive = false
      clearInterval(meter)
      setSentFps(0)
    }
  }, [opts.running, camera])

  const reset = useCallback(() => {
    setBurners([])
    setLastEvent(null)
  }, [])

  /** Switch who we're cooking for (changes salt/chili targets on the Mac). */
  const cycleProfile = useCallback(async () => {
    if (!profiles.length) return
    const i = profiles.findIndex((p) => p.id === profile?.id)
    const next = profiles[(i + 1) % profiles.length]
    setProfile(next)
    const http = url.replace(/^ws/, 'http').replace(/\/ws\/camera$/, '')
    try {
      await fetch(`${http}/api/profiles/active`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id: next.id }),
      })
    } catch {
      /* next summary will show the real profile */
    }
  }, [profiles, profile, url])

  return { conn, burners, serverFps, sentFps, lastEvent, reset, profile, cycleProfile, fogged }
}

/** Pick a small capture size: ~640px wide is all the vision pipeline uses. */
export function pickPictureSize(sizes: string[]): string | undefined {
  for (const preferred of ['640x480', '1280x720', 'Medium', 'Low']) if (sizes.includes(preferred)) return preferred
  const parsed = sizes
    .map((s) => ({ s, m: /^(\d+)x(\d+)$/.exec(s) }))
    .filter((x): x is { s: string; m: RegExpExecArray } => !!x.m)
    .map(({ s, m }) => ({ s, w: Math.max(+m[1], +m[2]) }))
    .sort((a, b) => a.w - b.w)
  return (parsed.find((p) => p.w >= 640) ?? parsed[parsed.length - 1])?.s
}

export const fmt = (s: number) => {
  const t = Math.max(0, Math.floor(s))
  return `${String(Math.floor(t / 60)).padStart(2, '0')}:${String(t % 60).padStart(2, '0')}`
}
