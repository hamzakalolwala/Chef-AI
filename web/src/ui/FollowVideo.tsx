import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import { MOCK } from '../lib/mock'
import type { Burner, FollowState, Pantry, VideoItem, VideoRecipe } from '../lib/types'
import { Modal } from './Modals'

export const mmss = (t: number | null) => (t == null ? '—' : `${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, '0')}`)
const watchAt = (url: string, t: number | null) => (t == null ? url : `${url}${url.includes('?') ? '&' : '?'}t=${Math.floor(t)}s`)

type Recent = Awaited<ReturnType<typeof api.videos>>

/** Paste a YouTube recipe → review what Sous Chef AI read → follow it on a burner. */
export function FollowVideo({ pantry, burners, onClose }: { pantry: Pantry; burners: Burner[]; onClose: () => void }) {
  const [url, setUrl] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [recipe, setRecipe] = useState<VideoRecipe | null>(null)
  const [recent, setRecent] = useState<Recent>([])
  const [servings, setServings] = useState<string>('')
  const [scale, setScale] = useState('1')
  const [burner, setBurner] = useState(burners[0]?.id ?? '')
  const [start, setStart] = useState(0)
  const [msg, setMsg] = useState<string | null>(null)

  useEffect(() => {
    api.videos().then(setRecent).catch(() => {})
  }, [])

  const load = (r: VideoRecipe) => {
    setRecipe(r)
    setServings(r.servings ? String(r.servings) : '')
    setScale('1')
    setStart(0)
    setMsg(null)
  }
  const read = async (link = url) => {
    setBusy(true)
    setErr(null)
    try {
      load(await api.readVideo(link))
    } catch (e) {
      setErr(String((e as Error).message))
    } finally {
      setBusy(false)
    }
  }
  const setItem = (i: number, patch: Partial<VideoItem>) =>
    recipe && setRecipe({ ...recipe, items: recipe.items.map((it, j) => (j === i ? { ...it, ...patch, source: 'edited' } : it)) })

  const follow = async () => {
    if (!recipe) return
    try {
      const saved = await api.saveVideo({ ...recipe, servings: servings ? Number(servings) : null })
      setRecipe(saved)
      await api.follow(burner, saved.id, Number(scale) || 1)
      setMsg(`Following on ${burners.find((b) => b.id === burner)?.name}. Sous Chef AI will beep if you add more than this.`)
    } catch (e) {
      setMsg(String((e as Error).message))
    }
  }

  const tracked = recipe?.items.filter((i) => i.ingredient && i.grams).length ?? 0

  return (
    <Modal title="Follow a recipe video" onClose={onClose} wide>
      <div className="row follow-bar">
        <input
          className="url-input"
          value={url}
          placeholder="Paste a YouTube link, e.g. https://youtu.be/…"
          onChange={(e) => setUrl(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && read()}
        />
        <button className="btn primary" disabled={busy || !url.trim()} onClick={() => read()}>
          {busy ? 'Reading…' : 'Read recipe'}
        </button>
      </div>
      <p className="hint">
        Sous Chef AI reads the video's description and captions (what the cook writes and says). It doesn't watch the
        video. Check the amounts below before you follow it.
      </p>
      {err && <p className="error">{err}</p>}

      {!recipe && recent.length > 0 && (
        <div className="recent">
          {recent.slice(0, 8).map((r) => (
            <button key={r.id} className="recent-item" onClick={() => api.video(r.id).then(load)}>
              {r.thumbnail && !MOCK && <img src={r.thumbnail} alt="" />}
              <span>{r.title}</span>
            </button>
          ))}
        </div>
      )}

      {recipe && (
        <div className="follow">
          <div className="follow-left">
            {MOCK ? (
              <a className="yt yt-link" href={`${recipe.url}${start ? `&t=${Math.floor(start)}s` : ''}`} target="_blank" rel="noreferrer">▶ Watch on YouTube{start ? ` from ${mmss(start)}` : ''}</a>
            ) : <iframe
              key={start}
              className="yt"
              src={`https://www.youtube-nocookie.com/embed/${recipe.id}?start=${Math.floor(start)}${start ? '&autoplay=1' : ''}`}
              title={recipe.title}
              allow="autoplay; encrypted-media; picture-in-picture"
              allowFullScreen
            />}
            <b>{recipe.title}</b>
            <span className="hint">
              {recipe.channel} · amounts from {recipe.caption_source ? 'description + captions' : 'description only (no usable captions)'}
            </span>
            <div className="scale">
              <label>Video makes<input type="number" min={1} value={servings} placeholder="?" onChange={(e) => setServings(e.target.value)} />servings</label>
              <label>
                You're making
                <input type="number" min={0.25} step={0.25} value={scale} onChange={(e) => setScale(e.target.value)} />× the video
              </label>
              {servings && (
                <div className="seg">
                  {[1, 2, 4, 6].map((n) => (
                    <button key={n} className={Number(scale) === n / Number(servings) ? 'active' : ''} onClick={() => setScale(String(+(n / Number(servings)).toFixed(3)))}>
                      for {n}
                    </button>
                  ))}
                </div>
              )}
            </div>
            <label className="scale">
              On burner
              <select value={burner} onChange={(e) => setBurner(e.target.value)}>
                {burners.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
              </select>
            </label>
            <button className="btn primary" onClick={follow} disabled={!tracked}>Follow this recipe</button>
            {!tracked && <p className="hint">No amounts found. Add them in the table first.</p>}
            {msg && <p className="hint">{msg}</p>}
          </div>

          <div className="follow-right">
            <table className="history items">
              <thead>
                <tr><th>When</th><th>Ingredient</th><th>Video amount</th><th>You add</th><th></th></tr>
              </thead>
              <tbody>
                {recipe.items.map((it, i) => (
                  <tr key={i} className={!it.ingredient ? 'muted' : ''} title={it.lines.join('\n')}>
                    <td>
                      {it.time != null ? <button className="chip" onClick={() => setStart(Math.max(0, it.time! - 3))}>▶ {mmss(it.time)}</button> : '—'}
                    </td>
                    <td>
                      <select value={it.ingredient ?? ''} onChange={(e) => setItem(i, { ingredient: e.target.value || null })}>
                        <option value="">{it.name} (not tracked)</option>
                        {pantry.ingredients.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
                      </select>
                    </td>
                    <td>
                      <input
                        className="grams"
                        type="number"
                        min={0}
                        step={0.5}
                        value={it.grams ?? ''}
                        placeholder={it.to_taste ? 'to taste' : 'g'}
                        onChange={(e) => setItem(i, { grams: e.target.value === '' ? null : Number(e.target.value), to_taste: e.target.value === '' })}
                      />{' '}g
                    </td>
                    <td className="you">{it.grams ? `${(it.grams * (Number(scale) || 1)).toFixed(it.grams * Number(scale) < 10 ? 1 : 0)} g` : 'your usual'}</td>
                    <td>
                      <button className="icon-btn" aria-label={`Remove ${it.name}`} onClick={() => setRecipe({ ...recipe, items: recipe.items.filter((_, j) => j !== i) })}>✕</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <button
              className="btn ghost"
              onClick={() => setRecipe({ ...recipe, items: [...recipe.items, { ingredient: 'salt', name: 'Salt', grams: null, to_taste: true, time: null, source: 'edited', lines: [] }] })}
            >
              + Add ingredient
            </button>
          </div>
        </div>
      )}
    </Modal>
  )
}

/** Compact "following a video" block for a burner card. */
export function FollowBadge({ b }: { b: Burner }) {
  const f: FollowState | null | undefined = b.session?.follow
  if (!f) return b.pending_follow ? <div className="follow-badge">📺 Will follow “{b.pending_follow}” when lit</div> : null
  const n = f.next
  return (
    <div className="follow-badge" onClick={(e) => e.stopPropagation()}>
      <div className="row">
        <a href={f.url} target="_blank" rel="noreferrer">📺 {f.title.length > 38 ? f.title.slice(0, 38) + '…' : f.title}</a>
        {f.scale !== 1 && <span className="hint">×{f.scale}</span>}
        <button className="chip ghost" title="Stop following" onClick={() => api.unfollow(b.id)}>✕</button>
      </div>
      {n ? (
        <div className="next">
          Next: <b>{n.name}</b> {n.target ? `${n.target < 10 ? n.target.toFixed(1) : Math.round(n.target)} g` : 'to taste'}
          {n.time != null && <a href={watchAt(f.url, n.time)} target="_blank" rel="noreferrer"> · video {mmss(n.time)}</a>}
        </div>
      ) : (
        <div className="next">✓ Everything from the video is in</div>
      )}
    </div>
  )
}
