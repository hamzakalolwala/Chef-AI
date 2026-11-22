import { useRef, useState } from 'react'
import { api, apiUrl } from '../lib/api'
import type { Burner, PhoneStatus, Zone } from '../lib/types'
import { Modal } from './Modals'

type Draft = { id: string; name: string; zone: Zone }
type Drag = { idx: number; mode: 'move' | 'resize'; startX: number; startY: number; orig: Zone }

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v))

/** Live camera view with draggable burner zones. Zones are what the vision pipeline crops. */
/** Remote control for the camera phone: nothing has to be tapped on the phone itself. */
function PhoneRemote({ phone }: { phone: PhoneStatus | null }) {
  const [err, setErr] = useState<string | null>(null)
  const run = (cmd: Parameters<typeof api.cameraCommand>[0], value?: number | boolean) => {
    setErr(null)
    api.cameraCommand(cmd, value).catch((e) => setErr(String(e.message)))
  }
  return (
    <div className="remote">
      <b>Phone remote</b>
      {phone && (
        <p className="hint">
          {phone.charging ? '⚡ charging' : '🔋 on battery'} {phone.battery != null ? `${phone.battery}%` : ''} · {phone.paused ? 'paused' : `${phone.fps} fps`}
        </p>
      )}
      <div className="row">
        <button className="btn" onClick={() => run(phone?.paused ? 'resume' : 'pause')}>{phone?.paused ? 'Resume' : 'Pause'}</button>
        <div className="seg">
          {[1, 2, 3].map((f) => (
            <button key={f} className={phone?.fps === f ? 'active' : ''} onClick={() => run('fps', f)}>{f} fps</button>
          ))}
        </div>
      </div>
      <div className="row">
        <button className="btn" onClick={() => run('torch', !phone?.torch)}>{phone?.torch ? 'Torch off' : 'Torch on'}</button>
        <button className="btn ghost" onClick={() => run('buzz')} title="Vibrate + flash the phone, to check which one it is">Buzz phone</button>
      </div>
      {err && <p className="error">{err}</p>}
    </div>
  )
}

export function CameraSetup({ burners, streaming, phone, onClose }: { burners: Burner[]; streaming: boolean; phone?: PhoneStatus | null; onClose: () => void }) {
  const [draft, setDraft] = useState<Draft[]>(() => burners.map(({ id, name, zone }) => ({ id, name, zone: { ...zone } })))
  const [msg, setMsg] = useState<string | null>(null)
  const box = useRef<HTMLDivElement>(null)
  const drag = useRef<Drag | null>(null)

  const onDown = (idx: number, mode: Drag['mode']) => (e: React.PointerEvent) => {
    e.stopPropagation()
    ;(e.target as HTMLElement).setPointerCapture(e.pointerId)
    drag.current = { idx, mode, startX: e.clientX, startY: e.clientY, orig: { ...draft[idx].zone } }
  }
  const onMove = (e: React.PointerEvent) => {
    const d = drag.current
    if (!d || !box.current) return
    const rect = box.current.getBoundingClientRect()
    const dx = (e.clientX - d.startX) / rect.width
    const dy = (e.clientY - d.startY) / rect.height
    setDraft((prev) =>
      prev.map((b, i) => {
        if (i !== d.idx) return b
        const o = d.orig
        const zone =
          d.mode === 'move'
            ? { ...o, x: clamp(o.x + dx, 0, 1 - o.w), y: clamp(o.y + dy, 0, 1 - o.h) }
            : { ...o, w: clamp(o.w + dx, 0.05, 1 - o.x), h: clamp(o.h + dy, 0.05, 1 - o.y) }
        return { ...b, zone }
      }),
    )
  }
  const onUp = () => (drag.current = null)

  const add = () => {
    const n = draft.length + 1
    let id = `b${n}`
    while (draft.some((d) => d.id === id)) id += 'x'
    setDraft([...draft, { id, name: `Burner ${n}`, zone: { x: 0.35, y: 0.35, w: 0.3, h: 0.3 } }])
  }

  const save = async () => {
    try {
      await api.saveZones(draft)
      setMsg('Saved ✓')
    } catch (e) {
      setMsg(String((e as Error).message))
    }
  }
  const baseline = async () => {
    try {
      await api.captureBaseline()
      setMsg('Baseline captured ✓ (all burners should be off)')
    } catch (e) {
      setMsg(String((e as Error).message))
    }
  }

  return (
    <Modal title="Camera & burner zones" onClose={onClose} wide>
      <div className="setup">
        <div className="frame" ref={box} onPointerMove={onMove} onPointerUp={onUp}>
          {streaming ? (
            <img src={apiUrl('/api/stream.mjpg')} alt="Live camera" draggable={false} />
          ) : (
            <div className="no-feed">No camera yet — connect the phone to see the live view. You can still lay out zones.</div>
          )}
          {draft.map((b, i) => (
            <div
              key={b.id}
              className="zone"
              style={{ left: `${b.zone.x * 100}%`, top: `${b.zone.y * 100}%`, width: `${b.zone.w * 100}%`, height: `${b.zone.h * 100}%` }}
              onPointerDown={onDown(i, 'move')}
            >
              <span>{b.name}</span>
              <i className="handle" onPointerDown={onDown(i, 'resize')} />
            </div>
          ))}
        </div>
        <div className="setup-side">
          <p className="hint">Drag a box over each burner (corner to resize). Image top = back of the stove.</p>
          {draft.map((b, i) => (
            <div className="zone-row" key={b.id}>
              <input value={b.name} onChange={(e) => setDraft(draft.map((d, j) => (j === i ? { ...d, name: e.target.value } : d)))} />
              <button className="icon-btn" disabled={draft.length <= 1} onClick={() => setDraft(draft.filter((_, j) => j !== i))} aria-label={`Remove ${b.name}`}>✕</button>
            </div>
          ))}
          <button className="btn ghost" onClick={add} disabled={draft.length >= 8}>+ Add burner</button>
          <hr />
          <button className="btn" onClick={baseline} disabled={!streaming}>Capture flame baseline</button>
          <p className="hint">With every burner OFF, this learns any blue things in view (pans, tiles) so they aren't mistaken for flames.</p>
          <button className="btn primary" onClick={save}>Save zones</button>
          {msg && <p className="hint">{msg}</p>}
          {phone !== undefined && (
            <>
              <hr />
              <PhoneRemote phone={phone} />
            </>
          )}
        </div>
      </div>
    </Modal>
  )
}
