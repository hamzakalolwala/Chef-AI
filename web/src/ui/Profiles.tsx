import { useState } from 'react'
import { api, apiUrl } from '../lib/api'
import type { Pantry, Profile } from '../lib/types'
import { Modal } from './Modals'

const TUNABLE = ['salt', 'sugar', 'chili', 'turmeric', 'garam_masala', 'oil', 'ghee']
const FILLS = [
  { v: 1, label: 'Level' },
  { v: 1.25, label: 'Rounded' },
  { v: 1.5, label: 'Heaped' },
]

export function ProfileSwitcher({ pantry, activeId, onEdit }: { pantry: Pantry | null; activeId?: string; onEdit: () => void }) {
  if (!pantry) return null
  return (
    <div className="profile-switch">
      <select value={activeId ?? pantry.active_profile} onChange={(e) => api.setProfile(e.target.value)} aria-label="Cooking for">
        {pantry.profiles.map((p) => (
          <option key={p.id} value={p.id}>{p.emoji} {p.name}</option>
        ))}
      </select>
      <button className="btn ghost" onClick={onEdit}>Profiles</button>
    </div>
  )
}

/** Edit taste profiles: how much of each ingredient this person likes vs the standard recipe. */
export function ProfilesEditor({ pantry, onSaved, onClose }: { pantry: Pantry; onSaved: (p: Pantry) => void; onClose: () => void }) {
  const [draft, setDraft] = useState<Profile[]>(() => structuredClone(pantry.profiles))
  const [msg, setMsg] = useState<string | null>(null)
  const ingName = (id: string) => pantry.ingredients.find((i) => i.id === id)?.name ?? id
  const dal = pantry.recipes['dal'] ?? {}
  const saltTsp = pantry.ingredients.find((i) => i.id === 'salt')

  const update = (i: number, patch: Partial<Profile>) => setDraft(draft.map((p, j) => (j === i ? { ...p, ...patch } : p)))
  const add = () => {
    let n = draft.length + 1
    while (draft.some((p) => p.id === `person${n}`)) n++
    setDraft([...draft, { id: `person${n}`, name: `Person ${n}`, emoji: '🙂', multipliers: {}, tolerance: 0.15, fill: 1 }])
  }
  const save = async () => {
    try {
      onSaved(await api.saveProfiles(draft))
      setMsg('Saved ✓')
    } catch (e) {
      setMsg(String((e as Error).message))
    }
  }

  return (
    <Modal title="Taste profiles" onClose={onClose} wide>
      <p className="hint">
        Each profile scales the recipe amounts. Tadka beeps when what goes in passes the target by more than the tolerance.
        Pick who you're cooking for in the top bar.
      </p>
      <div className="profiles">
        {draft.map((p, i) => {
          const saltTarget = (dal['salt'] ?? 0) * (p.multipliers['salt'] ?? 1)
          return (
            <div className="profile-card" key={p.id}>
              <div className="row">
                <input className="emoji" value={p.emoji} maxLength={4} onChange={(e) => update(i, { emoji: e.target.value })} aria-label="Emoji" />
                <input className="pname" value={p.name} onChange={(e) => update(i, { name: e.target.value })} aria-label="Profile name" />
                <button className="icon-btn" disabled={draft.length <= 1} onClick={() => setDraft(draft.filter((_, j) => j !== i))} aria-label={`Remove ${p.name}`}>✕</button>
              </div>
              {TUNABLE.map((ing) => {
                const v = p.multipliers[ing] ?? 1
                return (
                  <label key={ing} className="slider">
                    <span>{ingName(ing)}</span>
                    <input type="range" min={0} max={2} step={0.05} value={v}
                      onChange={(e) => update(i, { multipliers: { ...p.multipliers, [ing]: Number(e.target.value) } })} />
                    <b className={v > 1.05 ? 'more' : v < 0.95 ? 'less' : ''}>{v.toFixed(2)}×</b>
                  </label>
                )
              })}
              <label className="slider">
                <span>Beep when over by</span>
                <input type="range" min={0.05} max={0.5} step={0.05} value={p.tolerance} onChange={(e) => update(i, { tolerance: Number(e.target.value) })} />
                <b>{Math.round(p.tolerance * 100)}%</b>
              </label>
              <div className="slider">
                <span>Their spoons are usually</span>
                <div className="seg">
                  {FILLS.map((f) => (
                    <button key={f.v} className={p.fill === f.v ? 'active' : ''} onClick={() => update(i, { fill: f.v })}>{f.label}</button>
                  ))}
                </div>
              </div>
              {saltTsp && (
                <p className="hint">
                  e.g. Dal → {saltTarget.toFixed(1)} g salt ≈ {(saltTarget / (5 * saltTsp.density * p.fill)).toFixed(1)} tsp
                </p>
              )}
            </div>
          )
        })}
        <button className="profile-card add" onClick={add}>+ Add person</button>
      </div>
      <div className="row" style={{ marginTop: 12 }}>
        <button className="btn primary" onClick={save}>Save profiles</button>
        {msg && <span className="hint">{msg}</span>}
      </div>
    </Modal>
  )
}

/** Printable stickers: big name for humans + ArUco marker for the camera. */
export function LabelsSheet({ pantry, onClose }: { pantry: Pantry; onClose: () => void }) {
  const items = [
    ...pantry.ingredients.filter((i) => i.marker != null).map((i) => ({ key: i.id, name: i.name, marker: i.marker!, sub: 'box / lid', color: i.color })),
    ...pantry.spoons.filter((s) => s.marker != null).map((s) => ({ key: s.id, name: s.name, marker: s.marker!, sub: `${s.ml} ml spoon`, color: '#888' })),
  ]
  return (
    <Modal title="Print labels" onClose={onClose} wide>
      <div className="no-print">
        <p className="hint">
          Stick each label on top of its box (facing up, toward the camera) and on each spoon's handle near the bowl.
          The camera reads the square code; the name is for you. When a spoon touches a box and then goes over a pot, that's one spoonful.
          Print at 100% scale. Codes print about 6 cm wide; smaller ones get missed when the spoon moves. A measuring-spoon set (¼, ½, 1 tsp, 1 tbsp) with one label each makes amounts exact.
        </p>
        <button className="btn primary" onClick={() => window.print()}>Print</button>
      </div>
      <div className="print-sheet">
        {items.map((it) => (
          <div className="sticker" key={it.key} style={{ ['--c' as string]: it.color }}>
            <img src={apiUrl(`/api/markers/${it.marker}.png`)} alt={`Marker ${it.marker} for ${it.name}`} />
            <div>
              <b>{it.name}</b>
              <span>{it.sub} · #{it.marker}</span>
            </div>
          </div>
        ))}
      </div>
    </Modal>
  )
}
