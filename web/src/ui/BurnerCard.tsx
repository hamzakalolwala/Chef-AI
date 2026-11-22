import { useState } from 'react'
import { api } from '../lib/api'
import { STATUS_LABEL, ago, clock, minutes, progressColor } from '../lib/format'
import type { Burner, Dish, Pantry } from '../lib/types'
import { IngredientPanel } from './Ingredients'
import { FollowBadge } from './FollowVideo'

function Editor({ b, dishes, onDone }: { b: Burner; dishes: Dish[]; onDone: () => void }) {
  const s = b.session
  const [dish, setDish] = useState<string>(s?.overridden ? s.dish_id ?? '__custom' : '')
  const [label, setLabel] = useState(s?.overridden && !s.dish_id ? s.dish ?? '' : '')
  const [target, setTarget] = useState<string>(s?.target_seconds ? String(Math.round(s.target_seconds / 60)) : '')
  const [batch, setBatch] = useState<string>(String(s?.batch ?? 1))
  const [err, setErr] = useState<string | null>(null)

  const apply = async () => {
    try {
      await api.setOverride(b.id, {
        dish_id: dish && dish !== '__custom' ? dish : null,
        label: dish === '__custom' && label.trim() ? label.trim() : null,
        target_minutes: target ? Number(target) : null,
        batch: batch ? Number(batch) : null,
      })
      onDone()
    } catch (e) {
      setErr(String((e as Error).message))
    }
  }

  return (
    <div className="editor" onClick={(e) => e.stopPropagation()}>
      <label>
        Dish
        <select value={dish} onChange={(e) => {
          setDish(e.target.value)
          const d = dishes.find((x) => x.id === e.target.value)
          if (d) setTarget(String(d.minutes))
        }}>
          <option value="">Auto-detect</option>
          {dishes.map((d) => (
            <option key={d.id} value={d.id}>{d.name}</option>
          ))}
          <option value="__custom">Something else…</option>
        </select>
      </label>
      {dish === '__custom' && (
        <label>
          Name
          <input value={label} placeholder="e.g. Nani's kheer" onChange={(e) => setLabel(e.target.value)} />
        </label>
      )}
      <label>
        Target (min)
        <input type="number" min={1} max={600} value={target} placeholder="auto" onChange={(e) => setTarget(e.target.value)} />
      </label>
      <label>
        Batch size (× standard recipe, ~4 servings)
        <input type="number" min={0.25} max={10} step={0.25} value={batch} onChange={(e) => setBatch(e.target.value)} />
      </label>
      <p className="hint">Correcting the dish also teaches the model what it looks like in your kitchen.</p>
      {err && <p className="error">{err}</p>}
      <div className="row">
        <button className="btn primary" onClick={apply}>Apply</button>
        <button className="btn ghost" onClick={onDone}>Cancel</button>
      </div>
    </div>
  )
}

export function BurnerCard({ b, dishes, pantry, selected, onSelect }: {
  b: Burner
  dishes: Dish[]
  pantry: Pantry | null
  selected: boolean
  onSelect: (id: string | null) => void
}) {
  const [editing, setEditing] = useState(false)
  const s = b.session
  const color = progressColor(b)
  const pct = s?.progress != null ? Math.min(100, s.progress * 100) : 0
  const manual = b.flame.manual

  return (
    <div
      className={`card burner status-${b.status} ${selected ? 'selected' : ''}`}
      style={{ ['--accent' as string]: color }}
      onClick={() => onSelect(selected ? null : b.id)}
    >
      <div className="card-head">
        <span className={`flame-dot ${b.flame.on ? 'on' : ''}`} />
        <span className="burner-name">{b.name}</span>
        <span className="status-chip">{STATUS_LABEL[b.status]}</span>
      </div>

      <div className="dish-line">
        <span className="dish">{s?.dish ?? (s ? 'Identifying…' : '—')}</span>
        {s && !s.overridden && s.dish && <span className="conf">{Math.round(s.confidence * 100)}%</span>}
        {s?.overridden && <span className="conf you">set by you</span>}
      </div>

      {s ? (
        <>
          <div className="timer-row">
            <span className="timer">{clock(s.cook_seconds)}</span>
            <span className="target">{s.target_seconds ? `/ ${minutes(s.target_seconds)}` : ''}</span>
          </div>
          <div className="bar"><div style={{ width: `${pct}%` }} /></div>
          <div className="meta">
            <span title="Flame strength from the camera">🔥 {Math.round(b.flame.score * 100)}%</span>
            <span title="Stirs detected">🥄 {s.stirs}</span>
            <span title="Last time someone touched the pot">👋 {ago(s.since_attention)}</span>
          </div>
        </>
      ) : (
        b.top.length > 0 && (
          <div className="meta">
            <span>Seeing: {b.top.map((t) => `${t.name} ${Math.round(t.p * 100)}%`).join(' · ')}</span>
          </div>
        )
      )}

      <FollowBadge b={b} />
      <IngredientPanel b={b} pantry={pantry} expanded={selected && !editing} />

      {b.status === 'danger' && (
        <div className="actions" onClick={(e) => e.stopPropagation()}>
          <button className="btn danger" onClick={() => api.dismiss(b.id, 'empty_flame')}>There's a pot on it</button>
          <button className="btn" onClick={() => api.setFlame(b.id, false)}>I turned it off</button>
        </div>
      )}

      {selected && !editing && (
        <div className="actions" onClick={(e) => e.stopPropagation()}>
          <button className="btn" onClick={() => setEditing(true)}>Set dish / timer</button>
          <div className="seg" title="Override flame detection">
            {([['Auto', null], ['On', true], ['Off', false]] as const).map(([label, v]) => (
              <button key={label} className={manual === v ? 'active' : ''} onClick={() => api.setFlame(b.id, v)}>
                {label}
              </button>
            ))}
          </div>
          {s && <button className="btn ghost" onClick={() => api.reset(b.id)}>End session</button>}
        </div>
      )}
      {selected && editing && <Editor b={b} dishes={dishes} onDone={() => setEditing(false)} />}
    </div>
  )
}
