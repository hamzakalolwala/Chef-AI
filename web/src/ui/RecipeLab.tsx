import { useEffect, useMemo, useState } from 'react'
import { api } from '../lib/api'
import { MOCK } from '../lib/mock'
import type { Burner, LabEval, LabOptions, LabResult, Pantry } from '../lib/types'
import { Modal } from './Modals'

type Dish = 'chai' | 'tadka'
type Mode = 'upgrade' | 'new'

const FIELDS: Record<Dish, [string, string, 'g' | 'ml' | 's' | 'lvl' | 'c' | 'bool'][]> = {
  chai: [
    ['water_g', 'Water', 'ml'], ['milk_g', 'Milk', 'ml'], ['tea_g', 'Tea leaves', 'g'], ['sugar_g', 'Sugar', 'g'],
    ['ginger_g', 'Ginger', 'g'], ['cardamom_g', 'Cardamom', 'g'], ['tea_boil_s', 'Boil tea (before milk)', 's'],
    ['milk_simmer_s', 'Simmer after milk', 's'], ['level_tea', 'Heat while tea boils', 'lvl'],
    ['level_simmer', 'Heat after milk', 'lvl'], ['cardamom_last_s', 'Cardamom, before end', 's'],
    ['milk_with_water', 'Milk + water together from the start', 'bool'],
  ],
  tadka: [
    ['oil_g', 'Oil / ghee', 'g'], ['cumin_g', 'Jeera', 'g'], ['mustard_g', 'Mustard seeds', 'g'],
    ['level', 'Heat the oil on', 'lvl'], ['add_at_c', 'Add spices at', 'c'], ['fry_s', 'Crackle for', 's'],
    ['fry_level', 'Heat while frying', 'lvl'],
  ],
}
const CH: [string, string][] = [['sweet', 'Sweet'], ['bitter', 'Bitter'], ['astringent', 'Dry'], ['heat', 'Heat'], ['salty', 'Salty'], ['fat', 'Rich']]
const PRESET_CHAI = { tea_g: 8, tea_boil_s: 300, milk_simmer_s: 300, level_tea: 7, level_simmer: 5 }
const PRESET_TADKA = { level: 10, fry_level: 10 }

const mmss = (s: number) => `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, '0')}`
const lvlLabel = (src: string, l: number) =>
  src.startsWith('lpg') ? (l >= 8.5 ? 'high' : l >= 6.5 ? 'med-high' : l >= 4.5 ? 'medium' : l >= 2.5 ? 'low' : 'sim') : `${l} · ${Math.round(l * 200)} W`

function Curve({ before, after }: { before: LabEval; after?: LabEval }) {
  const lines = [before, after].filter(Boolean) as LabEval[]
  const tMax = Math.max(...lines.flatMap((l) => l.temps.map((p) => p[0])), 60)
  const yMax = Math.max(110, ...lines.flatMap((l) => l.temps.map((p) => p[1]))) + 10
  const W = 420, H = 150, P = 28
  const x = (t: number) => P + ((W - P - 8) * t) / tMax
  const y = (c: number) => H - P + -((H - P - 8) * (c - 20)) / (yMax - 20)
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="curve" role="img" aria-label="Temperature over time">
      {[50, 100, 150, 200].filter((c) => c < yMax).map((c) => (
        <g key={c}><line x1={P} x2={W - 8} y1={y(c)} y2={y(c)} className="grid" /><text x={2} y={y(c) + 3}>{c}°</text></g>
      ))}
      {[0, tMax / 2, tMax].map((t) => <text key={t} x={x(t) - 10} y={H - 8}>{mmss(t)}</text>)}
      {lines.map((l, i) => (
        <polyline key={i} className={i === 0 && after ? 'before' : 'after'} fill="none"
          points={l.temps.map((p) => `${x(p[0]).toFixed(1)},${y(p[1]).toFixed(1)}`).join(' ')} />
      ))}
    </svg>
  )
}

function Bars({ before, after, when }: { before: LabEval; after?: LabEval; when: 'sip' | 'after' }) {
  const b = before.people[0]?.[when] ?? {}
  const a = after?.people[0]?.[when]
  return (
    <div className="lab-bars">
      {CH.filter(([c]) => (b[c] ?? 0) > 0.2 || (a?.[c] ?? 0) > 0.2).map(([c, label]) => (
        <div key={c} className="lab-bar">
          <span>{label}</span>
          <div className="track">
            <div className="b" style={{ width: `${(b[c] ?? 0) * 10}%` }} />
            {a && <div className="a" style={{ width: `${(a[c] ?? 0) * 10}%` }} />}
          </div>
          <b>{(b[c] ?? 0).toFixed(1)}{a ? ` → ${(a[c] ?? 0).toFixed(1)}` : ''}</b>
        </div>
      ))}
    </div>
  )
}

/** Fix an old recipe (e.g. chai with a bitter aftertaste) or create a new one, for LPG or induction. */
export function RecipeLab({ pantry, burners, onClose }: { pantry: Pantry; burners: Burner[]; onClose: () => void }) {
  const [opts, setOpts] = useState<LabOptions | null>(null)
  const [dish, setDish] = useState<Dish>('chai')
  const [mode, setMode] = useState<Mode>('upgrade')
  const hasInduction = burners.some((b) => b.source === 'induction')
  const [source, setSource] = useState<string>('lpg_large')
  const [vessel, setVessel] = useState<string>('')
  const [people, setPeople] = useState<string[]>([pantry.active_profile])
  const [recipe, setRecipe] = useState<Record<string, number | boolean>>({})
  const [result, setResult] = useState<(LabResult & { preview?: boolean }) | null>(null)
  const [taste, setTaste] = useState<LabEval | null>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    api.labOptions().then((o) => {
      setOpts(o)
      setRecipe({ ...o.dishes.chai, ...PRESET_CHAI })
    }).catch((e) => setErr(String(e.message)))
  }, [])
  const vessels = useMemo(() => (opts?.vessels ?? []).filter((v) => source !== 'induction' || v.induction_ok), [opts, source])
  useEffect(() => {
    if (vessel && !vessels.some((v) => v.id === vessel)) setVessel('')
  }, [vessels, vessel])

  const pickDish = (d: Dish) => {
    setDish(d)
    setResult(null)
    setTaste(null)
    if (opts) setRecipe({ ...opts.dishes[d], ...(d === 'chai' ? PRESET_CHAI : PRESET_TADKA) })
  }
  const body = (m: string) => ({ dish, recipe: mode === 'new' && m !== 'evaluate' ? {} : recipe, source, vessel: vessel || null, profile_ids: people, mode: m })
  const run = async (m: string) => {
    setBusy(true)
    setErr(null)
    try {
      const r = await api.lab(body(m))
      if (m === 'evaluate') {
        setTaste(r as LabEval)
        setResult(null)
      } else {
        setResult(r as LabResult)
        setTaste(null)
      }
    } catch (e) {
      setErr(String((e as Error).message))
    } finally {
      setBusy(false)
    }
  }
  const before = result?.before ?? taste
  const after = result?.after

  return (
    <Modal title="Recipe Lab" onClose={onClose} wide>
      <div className="lab-top">
        <div className="seg">
          {(['chai', 'tadka'] as Dish[]).map((d) => (
            <button key={d} className={dish === d ? 'active' : ''} onClick={() => pickDish(d)}>{d === 'chai' ? 'Chai' : 'Dal tadka'}</button>
          ))}
        </div>
        <div className="seg">
          <button className={mode === 'upgrade' ? 'active' : ''} onClick={() => setMode('upgrade')}>Fix my recipe</button>
          <button className={mode === 'new' ? 'active' : ''} onClick={() => setMode('new')}>Create a new one</button>
        </div>
        <label>Cooking on
          <select value={source} onChange={(e) => setSource(e.target.value)}>
            {(opts?.sources ?? []).map((s) => <option key={s.id} value={s.id}>{s.name}{s.id === 'induction' && hasInduction ? ' (yours)' : ''}</option>)}
          </select>
        </label>
        <label>Pot
          <select value={vessel} onChange={(e) => setVessel(e.target.value)}>
            <option value="">{dish === 'chai' ? 'Steel saucepan' : 'Cast-iron kadhai'} (default)</option>
            {vessels.map((v) => <option key={v.id} value={v.id}>{v.name}</option>)}
          </select>
        </label>
        <div className="family">
          {pantry.profiles.map((p) => (
            <button key={p.id} className={`fam ${people.includes(p.id) ? 'good active' : ''}`}
              onClick={() => setPeople(people.includes(p.id) ? people.filter((x) => x !== p.id) : [...people, p.id])}>
              {p.emoji} {p.name}
            </button>
          ))}
        </div>
      </div>
      {source === 'induction' && <p className="hint">Induction needs a steel or cast-iron pot; aluminium and copper won't heat. It heats only the base, faster than LPG, so oil overshoots more easily.</p>}
      {MOCK && <p className="hint">Preview: shows results worked out in advance (chai fix and new, dal tadka fix). On your Mac the Lab works any recipe out live.</p>}

      <div className="lab">
        <div className="lab-form">
          {mode === 'upgrade' ? (
            <>
              <b>Your recipe {dish === 'chai' && <span className="hint">(pre-filled: strong chai boiled long; the usual cause of a bitter, dry aftertaste)</span>}</b>
              {FIELDS[dish].map(([k, label, unit]) => (
                <label key={k} className="lab-field">
                  <span>{label}</span>
                  {unit === 'bool' ? (
                    <input type="checkbox" checked={!!recipe[k]} onChange={(e) => setRecipe({ ...recipe, [k]: e.target.checked })} />
                  ) : unit === 'lvl' ? (
                    <>
                      <input type="range" min={1} max={10} step={1} value={Number(recipe[k] ?? 5)} onChange={(e) => setRecipe({ ...recipe, [k]: Number(e.target.value) })} />
                      <em>{lvlLabel(source, Number(recipe[k] ?? 5))}</em>
                    </>
                  ) : (
                    <>
                      <input type="number" min={0} step={unit === 's' ? 10 : 0.5} value={Number(recipe[k] ?? 0)}
                        onChange={(e) => setRecipe({ ...recipe, [k]: Number(e.target.value) })} />
                      <em>{unit === 's' ? mmss(Number(recipe[k] ?? 0)) : unit === 'c' ? '°C' : unit}</em>
                    </>
                  )}
                </label>
              ))}
              <div className="row">
                <button className="btn" disabled={busy} onClick={() => run('evaluate')}>Taste it</button>
                <button className="btn primary" disabled={busy || !people.length} onClick={() => run('upgrade')}>{busy ? 'Working…' : 'Fix it'}</button>
              </div>
            </>
          ) : (
            <>
              <b>New {dish === 'chai' ? 'chai' : 'dal tadka'} for the people selected above</b>
              <p className="hint">The Lab cooks hundreds of versions in simulation on your heat source, tastes each with everyone's simulated tongue (including the aftertaste) and keeps the best.</p>
              <button className="btn primary" disabled={busy || !people.length || dish === 'tadka'} onClick={() => run('new')}>{busy ? 'Working…' : 'Create recipe'}</button>
              {dish === 'tadka' && <p className="hint">For tadka, use "Fix my recipe".</p>}
            </>
          )}
          {err && <p className="error">{err}</p>}
        </div>

        <div className="lab-result">
          {!before && <p className="hint">Results show here: who likes it, what lingers on the tongue, what to change, and step-by-step timings for your burner.</p>}
          {before && (
            <>
              <div className="lab-scores">
                {before.people.map((p, i) => {
                  const a = after?.people[i]
                  return (
                    <div key={p.id} className="lab-score">
                      <span>{p.emoji} {p.name}</span>
                      <b className={(a ?? p).score >= 7.5 ? 'good' : (a ?? p).score >= 5 ? 'meh' : 'bad'}>
                        {after && <s>{p.score.toFixed(1)}</s>} {(a ?? p).score.toFixed(1)}/10
                      </b>
                      <small>{after ? (a?.complaint ?? 'no complaints') : (p.complaint ?? 'no complaints')}{after && p.complaint ? ` (was: ${p.complaint})` : ''}</small>
                    </div>
                  )
                })}
              </div>
              <div className="lab-cols">
                <div><h4>While sipping</h4><Bars before={before} after={after} when="sip" /></div>
                <div><h4>30 s after swallowing</h4><Bars before={before} after={after} when="after" /></div>
              </div>
              {result && (
                <>
                  <h4>What to change</h4>
                  {result.changes.length ? <ul className="lab-changes">{result.changes.map((c) => <li key={c}>{c}</li>)}</ul> : <p className="hint">Nothing: it's already as good as it gets for these people.</p>}
                  <h4>Steps on {opts?.sources.find((s) => s.id === result.source)?.name}</h4>
                  <ol className="lab-steps">{result.steps.map((s, i) => <li key={i}><time>{mmss(s.t)}</time>{s.text}</li>)}</ol>
                  <h4>Same recipe on your other burners</h4>
                  <div className="family">
                    {Object.entries(result.same_recipe_on_other_sources).map(([sid, v]) => (
                      <span key={sid} className={`fam ${!v ? 'bad' : v.score >= 7.5 ? 'good' : 'meh'}`}>
                        {opts?.sources.find((s) => s.id === sid)?.name}: {v ? `${v.score.toFixed(1)}/10${v.minutes ? ` · ${v.minutes} min` : ''}${v.complaints[0] ? ` · ${v.complaints[0]}` : ''}` : "pot doesn't work"}
                      </span>
                    ))}
                  </div>
                </>
              )}
              <h4>Temperature in the pot {after && <span className="hint">(grey: before · orange: after)</span>}</h4>
              <Curve before={before} after={after} />
            </>
          )}
        </div>
      </div>
    </Modal>
  )
}
