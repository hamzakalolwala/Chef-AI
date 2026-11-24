import { clock, minutes, progressColor } from '../lib/format'
import type { Burner } from '../lib/types'
import { labelEls } from '../scene/labels'

/** DOM labels that float over each burner; positioned by scene/labels.ts every frame. */
export function LabelLayer({ burners }: { burners: Burner[] }) {
  return (
    <div className="labels">
      {burners.map((b) => {
        const s = b.session
        const hidden = !s && b.status !== 'ready'
        return (
          <div
            key={b.id}
            className="label-anchor"
            ref={(el) => {
              if (el) labelEls.set(b.id, el)
              else labelEls.delete(b.id)
            }}
          >
            <div className={`tag tag-${b.status}`} style={{ ['--accent' as string]: progressColor(b), display: hidden ? 'none' : undefined }}>
              <div className="tag-dish">
                {s?.dish ?? (b.status === 'ready' ? 'Pot ready' : 'Identifying…')}
                {s && !s.overridden && s.dish && <span className="tag-conf">{Math.round(s.confidence * 100)}%</span>}
              </div>
              {s && <div className="tag-time">{clock(s.cook_seconds)}</div>}
              {s?.ingredients.filter((r) => r.state === 'over').map((r) => (
                <div key={r.id} className="tag-warn">too much {r.name.toLowerCase()}</div>
              ))}
              {s && (
                <div className="tag-sub">
                  {s.target_seconds ? `of ${minutes(s.target_seconds)}` : b.flame.on ? (b.source === 'induction' ? 'heating' : 'on the flame') : 'off'}
                  {b.status === 'danger' && ' · nothing on it!'}
                </div>
              )}
            </div>
          </div>
        )
      })}
    </div>
  )
}
