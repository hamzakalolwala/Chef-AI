import { useEffect, useState } from 'react'
import { api, apiUrl } from './lib/api'
import type { KitchenEvent } from './lib/types'
import { MOCK } from './lib/mock'
import { useKitchen } from './lib/useKitchen'
import { announce, chime } from './lib/voice'
import { Kitchen } from './scene/Kitchen'
import { BurnerCard } from './ui/BurnerCard'
import { CameraSetup } from './ui/CameraSetup'
import { LabelLayer } from './ui/LabelLayer'
import { LabelsSheet, ProfileSwitcher, ProfilesEditor } from './ui/Profiles'
import { FollowVideo } from './ui/FollowVideo'
import { RecipeLab } from './ui/RecipeLab'
import type { SprinkleCue } from './scene/BurnerUnit'
import { ConnectPhone, History } from './ui/Modals'

type Panel = null | 'connect' | 'camera' | 'history' | 'profiles' | 'labels' | 'video' | 'lab'

const loadPref = (k: string, d: boolean) => {
  try {
    const v = localStorage.getItem(k)
    return v == null ? d : v === '1'
  } catch {
    return d
  }
}
const savePref = (k: string, v: boolean) => {
  try {
    localStorage.setItem(k, v ? '1' : '0')
  } catch {
    /* private mode */
  }
}

export default function App() {
  const { state, events, dishes, info, connected, onEvent, pantry, setPantry } = useKitchen()
  const [sprinkles, setSprinkles] = useState<Record<string, SprinkleCue>>({})
  const [selected, setSelected] = useState<string | null>(null)
  const [panel, setPanel] = useState<Panel>(null)
  const [voice, setVoice] = useState(() => loadPref('souschef.voice', true))
  const [toasts, setToasts] = useState<KitchenEvent[]>([])

  useEffect(
    () =>
      onEvent((ev) => {
        if (ev.ingredient && ev.burner_id) {
          const color = pantry?.ingredients.find((i) => i.id === ev.ingredient)?.color ?? '#ffffff'
          setSprinkles((s) => ({ ...s, [ev.burner_id!]: { key: ev.id, color } }))
        }
        if (ev.kind === 'profile') api.pantry().then(setPantry).catch(() => {})
        if (ev.level === 'info') return
        announce(ev, voice)
        if (voice) chime(ev.level)
        setToasts((t) => [...t.slice(-2), ev])
        setTimeout(() => setToasts((t) => t.filter((x) => x.id !== ev.id)), 9000)
      }),
    [onEvent, voice, pantry, setPantry],
  )

  const toggleVoice = () => {
    const v = !voice
    setVoice(v)
    savePref('souschef.voice', v)
    if (v && 'Notification' in window && Notification.permission === 'default') Notification.requestPermission()
  }

  const burners = state?.burners ?? []
  const cam = state?.camera
  const clf = state?.classifier ?? info?.classifier
  const active = burners.filter((b) => b.session && b.flame.on).length
  const empty = connected && !cam?.connected && !state?.demo

  return (
    <div className="app">
      <Kitchen burners={burners} selected={selected} onSelect={setSelected} sprinkles={sprinkles} />
      <LabelLayer burners={burners} />

      <header className="topbar">
        <div className="brand">
          <span className="logo">🍳</span>
          <div>
            <h1>Sous Chef AI</h1>
            <p>kitchen vision · {active ? `${active} burner${active > 1 ? 's' : ''} cooking` : 'stove idle'}</p>
          </div>
        </div>
        <div className="pills">
          <span className={`pill ${connected ? 'ok' : 'bad'}`}>{connected ? 'Server' : 'Server offline'}</span>
          <span className={`pill ${cam?.fogged ? 'bad' : cam?.streaming ? 'ok' : cam?.connected ? 'warn' : ''}`}
            title={cam?.clarity != null ? `View sharpness ${Math.round(cam.clarity * 100)}% of normal` : undefined}>
            📱 {cam?.fogged ? 'lens fogged — wipe it' : cam?.phone?.paused ? 'paused' : cam?.streaming ? `${cam.fps.toFixed(1)} fps` : cam?.connected ? 'connected, no frames' : 'no phone'}
            {cam?.phone?.battery != null && ` · ${cam.phone.charging ? '⚡' : '🔋'}${cam.phone.battery}%`}
          </span>
          <span className={`pill ${clf?.loading ? 'warn' : clf?.name.startsWith('clip') ? 'ok' : ''}`} title="Dish recognition model">
            🧠 {clf?.loading ? 'loading model…' : clf?.name.startsWith('clip') ? 'CLIP' : 'no dish model'}
          </span>
          {state?.demo && <span className="pill demo">{MOCK ? 'PREVIEW' : 'DEMO'}</span>}
        </div>
        <nav className="actions-top">
          <ProfileSwitcher pantry={pantry} activeId={state?.profile?.id} onEdit={() => setPanel('profiles')} />
          <button className="btn" onClick={() => setPanel('video')}>📺 Follow video</button>
          <button className="btn" onClick={() => setPanel('lab')}>🧪 Recipe Lab</button>
          <button className="btn" onClick={() => setPanel('connect')}>Connect phone</button>
          <button className="btn" onClick={() => setPanel('camera')}>Camera & zones</button>
          <button className="btn" onClick={() => setPanel('history')}>History</button>
          <button className="btn" onClick={() => setPanel('labels')}>Labels</button>
          <button className={`btn ${state?.demo ? 'primary' : 'ghost'}`} onClick={() => api.setDemo(!state?.demo)}>
            {state?.demo ? 'Stop demo' : 'Demo'}
          </button>
          <button className="icon-btn" onClick={toggleVoice} title={voice ? 'Voice alerts on' : 'Voice alerts off'}>
            {voice ? '🔊' : '🔇'}
          </button>
        </nav>
      </header>

      <aside className="sidebar">
        {burners.map((b) => (
          <BurnerCard key={b.id} b={b} dishes={dishes} pantry={pantry} selected={selected === b.id} onSelect={setSelected} />
        ))}
      </aside>

      <section className="feed">
        {cam?.streaming && (
          <button className="pip" onClick={() => setPanel('camera')} title="Open camera view">
            <img src={apiUrl('/api/stream.mjpg')} alt="Live stove camera" />
            <span>LIVE</span>
          </button>
        )}
        <ul>
          {events.slice(-7).reverse().map((e) => (
            <li key={e.id} className={`ev ev-${e.level}`}>
              <time>{new Date(e.ts * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</time>
              {e.message}
            </li>
          ))}
        </ul>
      </section>

      <div className="toasts">
        {toasts.map((t) => (
          <div key={t.id} className={`toast toast-${t.level}`}>{t.message}</div>
        ))}
      </div>

      {empty && (
        <div className="empty">
          <h2>Point your phone at the stove</h2>
          <p>Sous Chef AI watches each burner, recognises the dish, times how long it's been on the flame, and nudges you when it's done, unattended, or lit with nothing on it.</p>
          <div className="row">
            <button className="btn primary" onClick={() => setPanel('connect')}>Connect phone</button>
            <button className="btn" onClick={() => api.setDemo(true)}>Try the demo</button>
          </div>
        </div>
      )}
      {!connected && (
        <div className="empty">
          <h2>Can't reach the Sous Chef AI server</h2>
          <p>Start it with <code>cd backend && .venv/bin/python -m app</code> — this page reconnects automatically.</p>
        </div>
      )}

      {panel === 'connect' && <ConnectPhone info={info} onClose={() => setPanel(null)} />}
      {panel === 'camera' && <CameraSetup burners={burners} streaming={!!cam?.streaming} phone={cam?.connected ? cam.phone ?? null : undefined} onClose={() => setPanel(null)} />}
      {panel === 'history' && <History onClose={() => setPanel(null)} />}
      {panel === 'profiles' && pantry && <ProfilesEditor pantry={pantry} onSaved={setPantry} onClose={() => setPanel(null)} />}
      {panel === 'labels' && pantry && <LabelsSheet pantry={pantry} onClose={() => setPanel(null)} />}
      {panel === 'lab' && pantry && <RecipeLab pantry={pantry} burners={burners} onClose={() => setPanel(null)} />}
      {panel === 'video' && pantry && <FollowVideo pantry={pantry} burners={burners} onClose={() => { setPanel(null); api.pantry().then(setPantry).catch(() => {}) }} />}
    </div>
  )
}
