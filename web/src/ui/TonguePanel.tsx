import type { Burner, TasteChannel } from '../lib/types'

const SHOW: [TasteChannel, string][] = [['salty', 'Salty'], ['sweet', 'Sweet'], ['heat', 'Heat'], ['bitter', 'Bitter'], ['sour', 'Sour']]

/** What the simulated tongue tastes right now (bar) vs. this person's ideal (tick), and who'll like it. */
export function TonguePanel({ b, expanded }: { b: Burner; expanded: boolean }) {
  const t = b.session?.tongue
  if (!t) return null
  const now = t.intensity?.now
  const ideal = t.intensity?.ideal ?? {}
  return (
    <div className="tongue" onClick={(e) => expanded && e.stopPropagation()}>
      {expanded && now && (
        <div className="tongue-bars" title="Simulated taste receptors: intensity 0-10 (bar) vs. this profile's ideal (tick)">
          {SHOW.filter(([c]) => now[c] > 0.2 || (ideal[c] ?? 0) > 0.2).map(([c, label]) => {
            const id = ideal[c]
            const off = id != null ? now[c] - id : c === 'bitter' || c === 'sour' ? Math.max(0, now[c] - 1.5) : 0
            return (
              <div key={c} className={`tb ${Math.abs(off) > 1.2 ? 'tb-off' : ''}`}>
                <span>{label}</span>
                <div className="tb-track">
                  <div className="tb-fill" style={{ width: `${now[c] * 10}%` }} />
                  {id != null && <i style={{ left: `${id * 10}%` }} />}
                </div>
                <b>{now[c].toFixed(1)}</b>
              </div>
            )
          })}
        </div>
      )}
      <div className="family">
        {t.family.map((f) => (
          <span key={f.id} className={`fam ${f.liking >= 7.5 ? 'good' : f.liking >= 5 ? 'meh' : 'bad'} ${f.active ? 'active' : ''}`}
            title={`${f.name}: predicted liking ${f.liking}/10${f.complaint ? ` (${f.complaint})` : ''}`}>
            {f.emoji} {f.liking.toFixed(1)}{f.complaint ? ` · ${f.complaint}` : ''}
          </span>
        ))}
      </div>
    </div>
  )
}
