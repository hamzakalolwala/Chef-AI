import { useState } from 'react'
import { api } from '../lib/api'
import type { Burner, IngredientRow, Pantry } from '../lib/types'

const QUICK: { label: string; spoon: string; count: number }[] = [
  { label: 'pinch', spoon: 'pinch', count: 1 },
  { label: '½ tsp', spoon: 'tsp', count: 0.5 },
  { label: '1 tsp', spoon: 'tsp', count: 1 },
  { label: '1 tbsp', spoon: 'tbsp', count: 1 },
]

function Row({ r }: { r: IngredientRow }) {
  const scale = Math.max(r.limit ?? 0, r.grams, r.target ?? 0) || 1
  return (
    <div className={`ing-row ing-${r.state}`} title={r.target ? `target ${r.target} g, beeps above ${r.limit} g` : 'no target for this dish'}>
      <span className="ing-dot" style={{ background: r.color }} />
      <span className="ing-name">{r.name}</span>
      <div className="ing-bar">
        <div className="ing-fill" style={{ width: `${(r.grams / scale) * 100}%` }} />
        {r.target != null && <i className="ing-target" style={{ left: `${(r.target / scale) * 100}%` }} />}
      </div>
      <span className="ing-num">
        {r.grams.toFixed(r.grams < 10 ? 1 : 0)}{r.target != null ? `/${r.target.toFixed(r.target < 10 ? 1 : 0)}` : ''} g
      </span>
    </div>
  )
}

/** Ingredient progress vs. the active profile's targets, plus quick-add buttons. */
export function IngredientPanel({ b, pantry, expanded }: { b: Burner; pantry: Pantry | null; expanded: boolean }) {
  const s = b.session
  const [ing, setIng] = useState('salt')
  const [err, setErr] = useState<string | null>(null)
  if (!s) return null
  const rows = expanded ? s.ingredients : s.ingredients.filter((r) => r.grams > 0 || r.state === 'over')
  if (!expanded && rows.length === 0) return null

  const add = (spoon: string, count: number) => {
    setErr(null)
    api.addIngredient(b.id, ing, spoon, count).catch((e) => setErr(String(e.message)))
  }

  return (
    <div className="ingredients" onClick={(e) => expanded && e.stopPropagation()}>
      {rows.map((r) => <Row key={r.id} r={r} />)}
      {expanded && s.ingredients.length === 0 && <p className="hint">No recipe targets for this dish yet. Additions are still logged.</p>}
      {expanded && pantry && (
        <div className="quick-add">
          <select value={ing} onChange={(e) => setIng(e.target.value)} aria-label="Ingredient">
            {pantry.ingredients.map((i) => <option key={i.id} value={i.id}>{i.name}</option>)}
          </select>
          {QUICK.map((q) => (
            <button key={q.label} className="chip" onClick={() => add(q.spoon, q.count)}>+{q.label}</button>
          ))}
          <button className="chip ghost" onClick={() => api.undoIngredient(b.id)} title="Undo last addition">↶</button>
        </div>
      )}
      {err && <p className="error">{err}</p>}
    </div>
  )
}
