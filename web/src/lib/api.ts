import type { HistoryRow, Pantry, Profile, VideoRecipe, Zone } from './types'

// Same origin by default (Vite proxies /api and /ws in dev; the backend serves the build in prod).
// Override with ?server=192.168.1.20:8000
const override = new URLSearchParams(location.search).get('server')
const httpBase = override ? `http://${override}` : ''

export const apiUrl = (path: string) => `${httpBase}${path}`

export const wsUrl = (path: string) => {
  if (override) return `ws://${override}${path}`
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  return `${proto}://${location.host}${path}`
}

async function send<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(apiUrl(path), {
    method,
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}))
    throw new Error(detail?.detail ? String(detail.detail) : `${res.status} ${res.statusText}`)
  }
  return res.json() as Promise<T>
}

export const api = {
  setOverride: (id: string, body: { dish_id: string | null; label: string | null; target_minutes: number | null; batch?: number | null }) =>
    send('POST', `/api/burners/${id}/override`, body),
  setFlame: (id: string, on: boolean | null) => send('POST', `/api/burners/${id}/flame`, { on }),
  dismiss: (id: string, alert: 'empty_flame' | 'unattended' | 'target') => send('POST', `/api/burners/${id}/dismiss`, { alert }),
  addIngredient: (id: string, ingredient: string, spoon: string, count = 1) =>
    send('POST', `/api/burners/${id}/ingredient`, { ingredient, spoon, count }),
  addGrams: (id: string, ingredient: string, grams: number) => send('POST', `/api/burners/${id}/ingredient`, { ingredient, grams }),
  undoIngredient: (id: string) => send('POST', `/api/burners/${id}/ingredient/undo`),
  cameraCommand: (cmd: 'pause' | 'resume' | 'fps' | 'torch' | 'buzz', value?: number | boolean) =>
    send('POST', '/api/camera/command', { cmd, value }),
  readVideo: (url: string) => send<VideoRecipe>('POST', '/api/video/parse', { url }),
  videos: () => send<{ id: string; title: string; channel: string; thumbnail: string; url: string }[]>('GET', '/api/videos'),
  video: (id: string) => send<VideoRecipe>('GET', `/api/video/${id}`),
  saveVideo: (r: VideoRecipe) => send<VideoRecipe>('PUT', `/api/video/${r.id}`, { title: r.title, servings: r.servings, items: r.items }),
  follow: (burner: string, videoId: string, scale: number) => send('POST', `/api/burners/${burner}/follow`, { video_id: videoId, scale }),
  unfollow: (burner: string) => send('DELETE', `/api/burners/${burner}/follow`),
  pantry: () => send<Pantry>('GET', '/api/pantry'),
  setProfile: (pid: string) => send('POST', '/api/profiles/active', { id: pid }),
  saveProfiles: (profiles: Profile[], active?: string) => send<Pantry>('PUT', '/api/profiles', { profiles, active }),
  reset: (id: string) => send('POST', `/api/burners/${id}/reset`),
  setDemo: (enabled: boolean) => send('POST', '/api/demo', { enabled }),
  saveZones: (burners: { id: string; name: string; zone: Zone }[]) => send('PUT', '/api/zones', burners),
  captureBaseline: () => send('POST', '/api/calibrate/baseline'),
  history: () =>
    send<{ sessions: HistoryRow[]; stats: { dish: string; sessions: number; total_seconds: number; avg_seconds: number }[] }>(
      'GET',
      '/api/history?limit=100',
    ),
}
