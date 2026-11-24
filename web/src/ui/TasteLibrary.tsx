import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import { Modal } from './Modals'

type Range = { mid: number; lo: number; hi: number }
type Fingerprint = Record<string, { n: number; recipes: string[]; taste: Record<string, Range>; ranges: Record<string, [number, number]> }>
type RefRecipe = { name: string; category: string; items: { name: string; grams: number | null; ingredient: string | null }[] }
type Change = { ingredient: string; name: string; text: string; pct: number }
type Issue = { key: string; message: string; severity: string }
type Cut = { best: { size_mm: number; texture: string; fresh: number; cooked: number }; cut_words: string; shorter_time_s: number | null }
type AdaptResult = {
  name: string; category: string; learned_from: string[]; changes: Change[]; notes: string[]
  items: { name: string; grams: number | null; new_amount: string | null; ingredient: string | null }[]
  taste_before: Record<string, number>; taste_after: Record<string, number>; target: Record<string, Range> | null
  balance_before: Issue[]; balance_after: Issue[]; cuts: (Cut & { ingredient: string; size_mm: number | null })[]
}
const TASTES: [string, string][] = [['sweet', 'Sweet'], ['bitter', 'Bitter'], ['sour', 'Sour'], ['salty', 'Salty'], ['fat', 'Rich']]
const CATS = ['', 'cake', 'cookie', 'brownie', 'muffin', 'bread', 'dessert', 'savoury']

function SweetSpot({ fp }: { fp: Fingerprint }) {
  const cats = Object.entries(fp).filter(([c]) => c !== 'sweet')
  if (!cats.length) return null
  return (
    <div className="spot-grid">
      {cats.map(([cat, f]) => (
        <div className="spot" key={cat}>
          <b>{cat}</b> <span className="hint">from {f.n} recipe{f.n > 1 ? 's' : ''}</span>
          {TASTES.filter(([t]) => f.taste[t] && f.taste[t].hi > 0.2).map(([t, label]) => (
            <div className="spot-row" key={t}>
              <span>{label}</span>
              <div className="track">
                <div className="band" style={{ left: `${f.taste[t].lo * 10}%`, width: `${Math.max(1, (f.taste[t].hi - f.taste[t].lo) * 10)}%` }} />
                <i style={{ left: `${f.taste[t].mid * 10}%` }} />
              </div>
              <em>{f.taste[t].mid.toFixed(1)}</em>
            </div>
          ))}
        </div>
      ))}
    </div>
  )
}

/** Sister's recipes: import, learned sweet spot, adapt any recipe to it without breaking the balance. */
export function TasteLibrary({ onClose }: { onClose: () => void }) {
  const [refs, setRefs] = useState<RefRecipe[]>([])
  const [fp, setFp] = useState<Fingerprint>({})
  const [msg, setMsg] = useState<string | null>(null)
  const [text, setText] = useState('')
  const [name, setName] = useState('')
  const [cat, setCat] = useState('')
  const [videos, setVideos] = useState<{ id: string; title: string }[]>([])
  const [video, setVideo] = useState('')
  const [res, setRes] = useState<AdaptResult | null>(null)
  const [busy, setBusy] = useState(false)
  const [veg, setVeg] = useState('capsicum')
  const [fresh, setFresh] = useState(0.5)
  const [mins, setMins] = useState(4)
  const [cut, setCut] = useState<Cut | null>(null)

  const load = () => fetchJSON('/api/reference').then((d) => { setRefs(d.recipes); setFp(d.fingerprint) }).catch(() => {})
  useEffect(() => {
    load()
    api.videos().then(setVideos).catch(() => {})
  }, [])
  useEffect(() => {
    post('/api/cuts', { veg, want_fresh: fresh, seconds: mins * 60 }).then(setCut).catch(() => setCut(null))
  }, [veg, fresh, mins])

  const upload = async (f: File) => {
    setMsg('Reading…')
    const buf = new Uint8Array(await f.arrayBuffer())
    let bin = ''
    for (let i = 0; i < buf.length; i += 0x8000) bin += String.fromCharCode(...buf.subarray(i, i + 0x8000))
    try {
      const r = await post('/api/reference/import', { filename: f.name, data_b64: btoa(bin) })
      setMsg(`Learned from ${r.imported.length} recipes: ${r.imported.map((x: RefRecipe) => x.name).join(', ')}`)
      load()
    } catch (e) {
      setMsg(String((e as Error).message))
    }
  }
  const run = async () => {
    setBusy(true)
    setMsg(null)
    try {
      setRes(await post('/api/adapt', video ? { video_id: video, category: cat || null } : { text, name: name || 'Recipe', category: cat || null }))
    } catch (e) {
      setMsg(String((e as Error).message))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal title="Sister's recipes · our taste" onClose={onClose} wide>
      <div className="lib">
        <section>
          <h4>1 · Reference recipes</h4>
          <p className="hint">Upload the Excel or CSV sheet of the recipes you love. Any layout works: one row per ingredient, one row per recipe, or a column of ingredient text.</p>
          <label className="btn primary file">
            Upload sheet (.xlsx / .csv)
            <input type="file" accept=".xlsx,.xlsm,.csv,.tsv,.txt" onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} />
          </label>
          {refs.length > 0 && <p className="hint">{refs.length} recipes: {refs.map((r) => `${r.name} (${r.category})`).join(' · ')}</p>}
          {!refs.length && <p className="hint">No reference recipes yet. Until you add some, adapting uses general baking balance rules only.</p>}
          <h4>Our sweet spot</h4>
          <SweetSpot fp={fp} />
        </section>

        <section>
          <h4>2 · Adapt a recipe to our taste</h4>
          <select value={video} onChange={(e) => setVideo(e.target.value)} aria-label="From a YouTube recipe">
            <option value="">Paste a recipe below…</option>
            {videos.map((v) => <option key={v.id} value={v.id}>📺 {v.title}</option>)}
          </select>
          {!video && (
            <>
              <input className="lib-name" placeholder="Name (e.g. Pinterest vanilla sponge)" value={name} onChange={(e) => setName(e.target.value)} />
              <textarea rows={7} placeholder={'One ingredient per line, e.g.\nMaida 1½ cups\nSugar 1 cup\nButter 120 g\n2 eggs\nMilk ½ cup\nBaking powder 1½ tsp'}
                value={text} onChange={(e) => setText(e.target.value)} />
            </>
          )}
          <div className="row">
            <select value={cat} onChange={(e) => setCat(e.target.value)} aria-label="Kind of dish">
              {CATS.map((c) => <option key={c} value={c}>{c ? c : 'Kind: auto-detect'}</option>)}
            </select>
            <button className="btn primary" onClick={run} disabled={busy || (!video && !text.trim())}>{busy ? 'Balancing…' : 'Adapt to our taste'}</button>
          </div>
          {msg && <p className="hint">{msg}</p>}
          {res && (
            <div className="adapt">
              <p className="hint">{res.category} · {res.learned_from.length ? `tuned to: ${res.learned_from.join(', ')}` : 'no reference recipes for this kind yet: balance only'}</p>
              {res.changes.length ? <ul className="lab-changes">{res.changes.map((c) => <li key={c.ingredient}>{c.text}</li>)}</ul> : <p className="hint">Already right for your taste and well balanced.</p>}
              {res.notes.map((n) => <p key={n} className="hint">💡 {n}</p>)}
              <div className="lab-cols">
                <div>
                  <b>Balance</b>
                  {res.balance_before.length === 0 && <p className="hint">Was balanced.</p>}
                  {res.balance_before.map((i) => <p key={i.key} className="error">before: {i.message}</p>)}
                  {res.balance_after.map((i) => <p key={i.key} className="hint">still: {i.message}</p>)}
                  {res.balance_before.length > 0 && res.balance_after.length === 0 && <p className="hint">✓ balanced now</p>}
                </div>
                <div>
                  <b>Taste vs our sweet spot</b>
                  {TASTES.filter(([t]) => (res.taste_before[t] ?? 0) > 0.2 || (res.target?.[t]?.mid ?? 0) > 0.2).map(([t, label]) => (
                    <div className="spot-row" key={t}>
                      <span>{label}</span>
                      <div className="track">
                        {res.target?.[t] && <div className="band" style={{ left: `${res.target[t].lo * 10}%`, width: `${Math.max(1, (res.target[t].hi - res.target[t].lo) * 10)}%` }} />}
                        <i className="was" style={{ left: `${res.taste_before[t] * 10}%` }} />
                        <i style={{ left: `${res.taste_after[t] * 10}%` }} />
                      </div>
                      <em>{res.taste_before[t].toFixed(1)}→{res.taste_after[t].toFixed(1)}</em>
                    </div>
                  ))}
                </div>
              </div>
              <table className="history">
                <thead><tr><th>Ingredient</th><th>Original</th><th>For us</th></tr></thead>
                <tbody>
                  {res.items.map((i, k) => <tr key={k}><td>{i.name}</td><td>{i.grams != null ? `${Math.round(i.grams)} g` : '—'}</td><td>{i.new_amount ?? '—'}</td></tr>)}
                </tbody>
              </table>
              {res.cuts.map((c) => (
                <p key={c.ingredient} className="hint">🔪 {c.ingredient}: cut into {c.cut_words} (~{c.best.size_mm} mm) for a {c.best.texture} result{c.size_mm ? ` (recipe says ~${c.size_mm} mm)` : ''}.</p>
              ))}
            </div>
          )}
        </section>

        <section>
          <h4>3 · Cut size: fresh or cooked taste</h4>
          <div className="row">
            <select value={veg} onChange={(e) => setVeg(e.target.value)} aria-label="Vegetable">
              {['capsicum', 'onion', 'tomato', 'carrot', 'potato', 'paneer', 'beans'].map((v) => <option key={v}>{v}</option>)}
            </select>
            <label className="slider" style={{ flex: 1 }}>
              <span>Cooked ↔ Fresh</span>
              <input type="range" min={0} max={1} step={0.05} value={fresh} onChange={(e) => setFresh(Number(e.target.value))} />
              <b>{Math.round(fresh * 100)}%</b>
            </label>
            <label className="hint">for <input type="number" min={1} max={30} value={mins} onChange={(e) => setMins(Number(e.target.value))} style={{ width: 48 }} /> min</label>
          </div>
          {cut && (
            <p>
              Cut into <b>{cut.cut_words}</b> (~{cut.best.size_mm} mm): {cut.best.texture}, keeps {Math.round(cut.best.fresh * 100)}% of its fresh taste.
              {cut.shorter_time_s ? ` For a fresher result, cook it only ~${Math.round(cut.shorter_time_s / 60 * 10) / 10} min.` : ''}
            </p>
          )}
          <p className="hint">Small pieces have far more surface per gram: they cook through faster, lose the fresh green aroma sooner, brown more and soak up more oil. Big pieces stay crunchy and fresh in the middle.</p>
        </section>
      </div>
    </Modal>
  )
}

const fetchJSON = (path: string) => api.raw('GET', path)
const post = (path: string, body: unknown) => api.raw('POST', path, body)
