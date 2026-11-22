import * as Network from 'expo-network'

/**
 * Find the Tadka server on the local Wi-Fi without typing or scanning anything:
 * probe http://<every address in this phone's /24 subnet>:8000/api/info and take the first
 * one that answers like Tadka. ~254 tiny requests, done in parallel batches (a few seconds).
 */
export async function discoverServer(opts: { port?: number; hint?: string; onProgress?: (done: number, total: number) => void } = {}): Promise<string | null> {
  const port = opts.port ?? 8000

  // 1. The last known address is the most likely: try it first.
  if (opts.hint) {
    const host = opts.hint.replace(/^wss?:\/\//, '').split('/')[0]
    const hit = await probe(`http://${host}`, 1500)
    if (hit) return hit
  }

  // 2. Sweep the subnet.
  let ip: string
  try {
    ip = await Network.getIpAddressAsync()
  } catch {
    return null
  }
  const m = /^(\d+\.\d+\.\d+)\.(\d+)$/.exec(ip)
  if (!m) return null
  const prefix = m[1]
  const self = Number(m[2])
  // Routers/Macs are often low numbers; start near the phone's own address and fan out.
  const hosts = Array.from({ length: 254 }, (_, i) => i + 1)
    .filter((h) => h !== self)
    .sort((a, b) => Math.abs(a - self) - Math.abs(b - self))
  const BATCH = 32
  for (let i = 0; i < hosts.length; i += BATCH) {
    const batch = hosts.slice(i, i + BATCH)
    const results = await Promise.all(batch.map((h) => probe(`http://${prefix}.${h}:${port}`, 900)))
    opts.onProgress?.(Math.min(i + BATCH, hosts.length), hosts.length)
    const hit = results.find(Boolean)
    if (hit) return hit
  }
  return null
}

/** Returns the server's camera WebSocket URL if `base` is a Tadka server. */
async function probe(base: string, timeoutMs: number): Promise<string | null> {
  const ctrl = new AbortController()
  const timer = setTimeout(() => ctrl.abort(), timeoutMs)
  try {
    const res = await fetch(`${base}/api/info`, { signal: ctrl.signal })
    if (!res.ok) return null
    const info = await res.json()
    return typeof info?.camera_ws === 'string' ? info.camera_ws : null
  } catch {
    return null
  } finally {
    clearTimeout(timer)
  }
}
