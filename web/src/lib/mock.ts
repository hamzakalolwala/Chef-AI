/**
 * Preview mode: a simulated kitchen that runs entirely in the browser, so the dashboard can be shown
 * without the Python backend or a phone (build with VITE_MOCK=1, or open with ?mock=1).
 * Mirrors the backend's tracker rules closely enough to show the real UI flows.
 */
import dishesJson from '../../../backend/data/dishes.json'
import pantryJson from '../../../backend/data/pantry.json'
import labSamples from './labSamples.json'
import { liking as tLiking, perceive, stimulus as tStim } from './tongue'
import type { Burner, Dish, FollowState, KitchenEvent, KitchenState, Pantry, Profile, Status, VideoRecipe } from './types'

export const MOCK = import.meta.env.VITE_MOCK === '1' || new URLSearchParams(location.search).get('mock') === '1'

type Ing = { id: string; name: string; density: number; marker: number | null; color: string }
const INGS: Ing[] = (pantryJson as { ingredients: Ing[] }).ingredients
const SPOONS = (pantryJson as { spoons: { id: string; name: string; ml: number; marker: number | null }[] }).spoons
const RECIPES = (pantryJson as { recipes: Record<string, Record<string, number>> }).recipes
const DISHES: (Dish & { mass_g: number })[] = (dishesJson as { dishes: (Dish & { mass_g: number })[] }).dishes
const ing = (id: string) => INGS.find((i) => i.id === id)!
const gr = (g: number) => (g >= 10 ? g.toFixed(0) : g.toFixed(1).replace(/\.0$/, ''))

let profiles: Profile[] = [
  { id: 'me', name: 'Me', emoji: '🧑‍🍳', multipliers: {}, tolerance: 0.15, fill: 1 },
  { id: 'mild', name: 'Mild (less salt & chili)', emoji: '🌿', multipliers: { salt: 0.7, chili: 0.5, sugar: 0.8 }, tolerance: 0.1, fill: 1 },
]
let active = 'me'
const prof = () => profiles.find((p) => p.id === active) ?? profiles[0]

const COOKIES: VideoRecipe = {
  id: 'f-M3JN_7LGU', url: 'https://www.youtube.com/watch?v=f-M3JN_7LGU', title: "World's Best Chocolate Chip Cookies",
  channel: 'Honeysuckle', servings: 8, caption_source: 'subtitles:en',
  items: [
    { ingredient: 'butter', name: 'Butter', grams: 114, to_taste: false, time: 49, source: 'description', lines: ['1/2 cup (114g) butter'] },
    { ingredient: 'sugar', name: 'Sugar', grams: 100, to_taste: false, time: 106, source: 'description', lines: ['1/2 cup (100g) sugar'] },
    { ingredient: 'brown_sugar', name: 'Brown sugar', grams: 110, to_taste: false, time: 106, source: 'description', lines: ['1/2 cup (110g) brown sugar'] },
    { ingredient: 'vanilla', name: 'Vanilla', grams: 5, to_taste: false, time: 143, source: 'description', lines: ['1 tsp vanilla'] },
    { ingredient: 'salt', name: 'Salt', grams: 3, to_taste: false, time: 143, source: 'description', lines: ['1/2 tsp salt'] },
    { ingredient: 'baking_soda', name: 'Baking soda', grams: 2.75, to_taste: false, time: 143, source: 'description', lines: ['1/2 tsp baking soda'] },
    { ingredient: 'flour', name: 'Flour', grams: 160, to_taste: false, time: 147, source: 'description', lines: ['1 1/4 cups (160g) flour'] },
    { ingredient: 'chocolate_chips', name: 'Chocolate chips', grams: 175, to_taste: false, time: 147, source: 'description', lines: ['1 cup (175g) chocolate chips'] },
  ],
}
const CHAI: VideoRecipe = {
  id: 'PBxQdK-NrRc', url: 'https://www.youtube.com/watch?v=PBxQdK-NrRc', title: 'Perfect Masala Chai', channel: 'Example channel',
  servings: 2, caption_source: 'auto:en-orig',
  items: [
    { ingredient: 'water', name: 'Water', grams: 240, to_taste: false, time: 22, source: 'captions', lines: [] },
    { ingredient: 'tea', name: 'Tea leaves', grams: 3.5, to_taste: false, time: 61, source: 'captions', lines: [] },
    { ingredient: 'sugar', name: 'Sugar', grams: 17, to_taste: false, time: 95, source: 'captions', lines: [] },
    { ingredient: 'milk', name: 'Milk', grams: 250, to_taste: false, time: 120, source: 'captions', lines: [] },
    { ingredient: 'cardamom', name: 'Cardamom', grams: 0.6, to_taste: false, time: 140, source: 'captions', lines: [] },
  ],
}
const videos: Record<string, VideoRecipe> = { [COOKIES.id]: COOKIES, [CHAI.id]: CHAI }

type MB = {
  id: string; name: string; zone: Burner['zone']; source: 'lpg_large' | 'lpg_small' | 'induction'
  lit: boolean; manual: boolean | null; session: boolean
  cook: number; started: number; dish: string | null; label: string | null; target: number | null; batch: number
  stirs: number; lastAttention: number; ingredients: Record<string, number>; log: { ing: string; g: number }[]
  follow: { video: VideoRecipe; scale: number } | null; fired: Set<string>; offSince: number | null
}
const ZONES = [
  { id: 'b1', name: 'Back left', zone: { x: 0.06, y: 0.08, w: 0.4, h: 0.4 } },
  { id: 'b2', name: 'Back right', zone: { x: 0.54, y: 0.08, w: 0.4, h: 0.4 } },
  { id: 'b3', name: 'Front left', zone: { x: 0.06, y: 0.52, w: 0.4, h: 0.4 } },
  { id: 'b4', name: 'Front right', zone: { x: 0.54, y: 0.52, w: 0.4, h: 0.4 }, source: 'induction' as const },
]
let burners: MB[] = []
let events: KitchenEvent[] = []
let t0 = performance.now() / 1000
let eventId = 1
const listeners = new Set<(m: unknown) => void>()
const now = () => Date.now() / 1000
const clock = () => performance.now() / 1000 - t0

function emit(b: MB | null, kind: string, message: string, level: KitchenEvent['level'] = 'info', extra: Partial<KitchenEvent> = {}) {
  const ev: KitchenEvent = { id: eventId++, ts: now(), burner_id: b?.id ?? null, kind, level, message, ...extra }
  events = [...events.slice(-119), ev]
  listeners.forEach((fn) => fn({ type: 'event', event: ev }))
}

function fresh(z: (typeof ZONES)[number]): MB {
  return { source: 'lpg_large', ...z, lit: false, manual: null, session: false, cook: 0, started: 0, dish: null, label: null, target: null, batch: 1,
    stirs: 0, lastAttention: now(), ingredients: {}, log: [], follow: null, fired: new Set(), offSince: null }
}

function start(b: MB, dish: string | null, cookSeconds: number) {
  Object.assign(b, { lit: true, session: true, cook: cookSeconds, started: now() - cookSeconds, dish, lastAttention: now() })
}

function targets(b: MB, who?: Profile): Record<string, number> {
  const p = who ?? prof()
  const f = (k: string) => p.multipliers[k] ?? 1
  const base: Record<string, number> = {}
  for (const [k, v] of Object.entries(RECIPES[b.dish ?? ''] ?? {})) base[k] = +(v * b.batch * f(k)).toFixed(2)
  if (!b.follow) return base
  const out: Record<string, number> = {}
  for (const it of b.follow.video.items) {
    if (!it.ingredient) continue
    if (it.grams) out[it.ingredient] = +(it.grams * b.follow.scale * f(it.ingredient)).toFixed(2)
    else if (base[it.ingredient]) out[it.ingredient] = base[it.ingredient]
  }
  return out
}

function addIngredient(b: MB, id: string, grams: number, label: string, camera = false) {
  if (!b.session) throw new Error(`${b.name} isn't cooking — set flame On first`)
  const before = b.ingredients[id] ?? 0
  const total = +(before + grams).toFixed(2)
  b.ingredients[id] = total
  b.log.push({ ing: id, g: grams })
  b.lastAttention = now()
  const name = ing(id).name.toLowerCase()
  const target = targets(b)[id]
  const x = { ingredient: id, grams }
  const p = prof()
  if (!target) {
    const t = targets(b)
    const mix: Record<string, string> = { salt: 'sugar', sugar: 'salt', baking_soda: 'baking_powder', baking_powder: 'baking_soda' }
    if (Object.keys(t).length && before === 0 && mix[id] && t[mix[id]]) {
      emit(b, 'mixup', `${ing(id).name} isn't in this recipe — did you mean ${ing(mix[id]).name.toLowerCase()}?`, 'warn', x)
    } else emit(b, 'ingredient', `${b.name}: +${label} ${name} (${gr(total)} g total)`, 'info', x)
    return
  }
  const limit = target * (1 + p.tolerance)
  if (total > limit && camera && before < 0.9 * target) {
    emit(b, 'check_spoon', `This recipe needs only ${gr(target)} g ${name} — if that was a full spoon, it's too much`, 'warn', x)
  } else if (total > limit) {
    const whose = b.follow ? 'the video uses' : `${p.name}'s limit is`
    emit(b, 'too_much', `Too much ${name}! ${gr(total)} g${b.follow ? '' : ` in ${dishName(b) ?? 'the pot'}`} — ${whose} ${gr(target)} g`, 'danger', x)
  } else if (total >= 0.9 * target && before < 0.9 * target) {
    emit(b, 'ingredient_ok', `${ing(id).name} is spot on for ${p.name}: ${gr(total)} of ${gr(target)} g`, 'success', x)
  } else {
    emit(b, 'ingredient', `${b.name}: +${label} ${name} — ${gr(total)} of ${gr(target)} g`, 'info', x)
    if (total + grams > limit) emit(b, 'careful', `Careful — another ${label} of ${name} would be too much`, 'warn', x)
  }
}

const dishOf = (b: MB) => DISHES.find((d) => d.id === b.dish) ?? null
const dishName = (b: MB) => b.label ?? dishOf(b)?.name ?? null

function taste(b: MB) {
  const t = targets(b)
  const mass = b.follow
    ? Math.max(300, b.follow.video.items.reduce((s, i) => s + (i.grams ?? 0), 0) * b.follow.scale)
    : (dishOf(b)?.mass_g ?? 800) * b.batch
  const rows = []
  const defs: [string, string[], number, string[]][] = [
    ['salty', ['salt'], 1.3, ['bland', 'needs a little salt', 'just right', 'a bit salty', 'too salty']],
    ['sweet', ['sugar', 'brown_sugar', 'honey'], 1.3, ['not sweet', 'a little less sweet', 'just right', 'a bit sweet', 'too sweet']],
    ['heat', ['chili'], 0.8, ['very mild', 'mild', 'just right', 'spicy', 'too spicy']],
  ]
  for (const [name, drivers, exp, words] of defs) {
    const g = drivers.reduce((s, d) => s + (b.ingredients[d] ?? 0), 0)
    const ideal = drivers.reduce((s, d) => s + (t[d] ?? 0), 0)
    if (!ideal && !g) continue
    const ratio = ideal ? g / ideal : 0
    const i = ratio < 0.7 ? 0 : ratio < 0.9 ? 1 : ratio <= 1.15 ? 2 : ratio <= 1.35 ? 3 : 4
    rows.push({ taste: name, grams: g, ideal_grams: ideal, concentration: g / mass, ratio, score: Math.min(10, 5 * ratio ** exp),
      verdict: words[i], level: i < 2 ? 'low' : i === 2 ? 'ok' : 'high' })
  }
  return rows
}

function tongue(b: MB) {
  if (!Object.keys(b.ingredients).length) return null
  const mass = b.follow
    ? Math.max(300, b.follow.video.items.reduce((s, i) => s + (i.grams ?? 0), 0) * b.follow.scale)
    : (dishOf(b)?.mass_g ?? 800) * b.batch
  const now = perceive(tStim(b.ingredients, mass, b.dish))
  let intensity = null
  const family = profiles.map((p) => {
    const ideal = perceive(tStim(targets(b, p), mass, b.dish))
    const [score, complaint] = tLiking(now, ideal)
    if (p.id === active) intensity = { now, ideal }
    return { id: p.id, name: p.name, emoji: p.emoji, liking: score, complaint, active: p.id === active }
  })
  return { intensity, family }
}

function snapshot(): Burner[] {
  const n = now()
  return burners.map((b) => {
    const flameOn = b.manual ?? b.lit
    const d = dishOf(b)
    const t = targets(b)
    const target = b.target ?? (d ? d.minutes * 60 : null)
    let status: Status = 'idle'
    if (b.session && flameOn) status = target && b.cook > target ? 'overdue' : 'cooking'
    else if (b.session) status = 'paused'
    const tol = prof().tolerance
    const rows = [...new Set([...Object.keys(t), ...Object.keys(b.ingredients)])].map((id) => {
      const g = b.ingredients[id] ?? 0
      const tg = t[id] ?? null
      const state = !tg ? 'untracked' : g > tg * (1 + tol) ? 'over' : g >= 0.9 * tg ? 'ok' : 'under'
      return { id, name: ing(id)?.name ?? id, color: ing(id)?.color ?? '#ccc', grams: g, target: tg, limit: tg ? +(tg * (1 + tol)).toFixed(2) : null, state } as const
    })
    let follow: FollowState | null = null
    if (b.follow) {
      const steps = b.follow.video.items.map((it) => {
        const added = it.ingredient ? b.ingredients[it.ingredient] ?? 0 : 0
        const tg = it.ingredient ? t[it.ingredient] ?? null : null
        return { ingredient: it.ingredient, name: it.name, time: it.time, target: tg, added, to_taste: it.to_taste,
          done: !!added && (tg == null || added >= 0.9 * tg) }
      })
      follow = { id: b.follow.video.id, title: b.follow.video.title, url: b.follow.video.url, scale: b.follow.scale, steps,
        next: steps.find((s) => !s.done && s.ingredient) ?? null }
    }
    return {
      id: b.id, name: b.name, zone: b.zone, status, source: b.source,
      flame: { on: flameOn, score: flameOn ? 0.8 + Math.random() * 0.15 : 0.02, manual: b.manual },
      motion: flameOn ? 0.02 : 0, steam: flameOn ? 0.55 + 0.2 * Math.sin(n + b.zone.x * 9) : 0.05,
      occupied: b.session ? 0.95 : 0.05, lid: 0, pending_follow: null,
      top: b.session && d ? [{ id: d.id, name: d.name, p: 0.72 }] : [],
      session: b.session ? {
        started_at: b.started, cook_seconds: b.cook, target_seconds: target, progress: target ? b.cook / target : null,
        dish_id: b.label ? null : b.dish, dish: dishName(b), vessel: d?.vessel ?? 'pot', color: d?.color ?? '#c9a46a',
        confidence: b.label ? 1 : 0.72, overridden: !!b.label, stirs: b.stirs, since_attention: n - b.lastAttention,
        flame_off_for: b.offSince ? n - b.offSince : null, alerts: [...b.fired], batch: b.batch,
        ingredients: rows, follow, taste: taste(b), tongue: tongue(b),
      } : null,
    } as Burner
  })
}

// Scripted morning: dal gets one teaspoon of salt too many; chai follows a video; eggs come and go.
const SCRIPT: [number, (bs: MB[]) => void][] = [
  [6, (b) => addIngredient(b[0], 'turmeric', 1.4, '½ tsp', true)],
  [12, (b) => addIngredient(b[0], 'chili', 2.25, '1 tsp', true)],
  [15, (b) => { start(b[2], 'eggs', 0); emit(b[2], 'start', 'Front left lit — started timing') }],
  [20, (b) => addIngredient(b[0], 'salt', 6, '1 tsp', true)],
  [26, (b) => addIngredient(b[1], 'sugar', 12.75, '1 tbsp', true)],
  [34, (b) => addIngredient(b[0], 'salt', 6, '1 tsp', true)],
  [46, (b) => addIngredient(b[2], 'salt', 1.2, 'pinch', true)],
  [140, (b) => { b[2].lit = false; b[2].offSince = now(); emit(b[2], 'flame_off', 'Front left off after 2m 05s (Eggs / omelette)') }],
]
let scriptStep = 0

function reset() {
  burners = ZONES.map(fresh)
  start(burners[0], 'dal', 12 * 60)
  start(burners[1], 'chai', 3 * 60 + 20)
  burners[1].follow = { video: CHAI, scale: 1 }
  start(burners[3], 'rice', 17 * 60 + 30)
  t0 = performance.now() / 1000
  scriptStep = 0
  emit(null, 'demo', 'Preview: simulated kitchen (no phone or Mac server needed)', 'info')
}

let last = performance.now() / 1000
function tick() {
  const n = performance.now() / 1000
  const dt = Math.min(1, n - last)
  last = n
  while (scriptStep < SCRIPT.length && clock() >= SCRIPT[scriptStep][0]) {
    try { SCRIPT[scriptStep][1](burners) } catch { /* burner not cooking */ }
    scriptStep++
  }
  for (const b of burners) {
    const on = b.manual ?? b.lit
    if (on && !b.session) { start(b, b.dish, 0); emit(b, 'start', `${b.name} lit — started timing`) }
    if (on && b.session) {
      b.cook += dt
      if (Math.random() < dt / 70) { b.stirs++; b.lastAttention = now() }
      const target = b.target ?? (dishOf(b) ? dishOf(b)!.minutes * 60 : null)
      if (target && b.cook >= target && !b.fired.has('target')) {
        b.fired.add('target')
        emit(b, 'target', `${dishName(b) ?? 'Food'} on ${b.name} has cooked ${Math.floor(b.cook / 60)}m ${String(Math.floor(b.cook % 60)).padStart(2, '0')}s — check it`, 'success')
      }
    }
  }
  const state: KitchenState = {
    type: 'state', ts: now(), burners: snapshot(), demo: true, profile: prof(),
    camera: { connected: false, streaming: false, fps: 0, last_frame_at: null, devices: [], fogged: false, phone: null },
    classifier: { name: 'clip:ViT-B-32', ready: true, loading: false, samples: {} },
  }
  listeners.forEach((fn) => fn(state))
}

export const mockPantry = (): Pantry => ({ ingredients: INGS, spoons: SPOONS, recipes: RECIPES, profiles, active_profile: active })

/** Stands in for the dashboard WebSocket. */
export function mockConnect(onMessage: (m: unknown) => void) {
  if (!burners.length) reset()
  listeners.add(onMessage)
  onMessage({
    type: 'hello', dishes: DISHES, pantry: mockPantry(), events,
    info: { lan_ip: '192.168.1.20', port: 8000, camera_ws: 'ws://<your-mac>:8000/ws/camera', dashboard_url: 'http://<your-mac>:8000',
      classifier: { name: 'clip:ViT-B-32', ready: true, loading: false, samples: {} }, demo: true },
  })
  const timer = setInterval(tick, 250)
  return () => {
    clearInterval(timer)
    listeners.delete(onMessage)
  }
}

/** Stands in for the REST API. */
export async function mockSend(method: string, path: string, body?: any): Promise<any> {
  const m = /^\/api\/burners\/(\w+)\/(.*)$/.exec(path)
  const b = m ? burners.find((x) => x.id === m[1]) : undefined
  const fail = (msg: string) => Promise.reject(new Error(msg))
  if (m && !b) return fail('unknown burner')
  if (m && b) {
    switch (`${method} ${m[2]}`) {
      case 'POST flame': b.manual = body.on; if (body.on === false && b.session) b.offSince = now(); return { ok: true }
      case 'POST override':
        b.dish = body.dish_id ?? b.dish; b.label = body.label; b.target = body.target_minutes ? body.target_minutes * 60 : null
        if (body.batch) b.batch = body.batch
        if (body.label || body.dish_id) emit(b, 'override', `${b.name}: marked as ${body.label ?? dishOf(b)?.name}`)
        return { ok: true }
      case 'POST ingredient': {
        const sp = SPOONS.find((s) => s.id === body.spoon)
        const grams = body.grams ?? +((sp?.ml ?? 5) * (body.count ?? 1) * ing(body.ingredient).density * prof().fill).toFixed(2)
        try { addIngredient(b, body.ingredient, grams, body.grams ? `${body.grams} g` : `${body.count ?? 1} ${sp?.id ?? ''}`) } catch (e) { return fail((e as Error).message) }
        return { ok: true }
      }
      case 'POST ingredient/undo': {
        const l = b.log.pop()
        if (l) { b.ingredients[l.ing] = Math.max(0, (b.ingredients[l.ing] ?? 0) - l.g); emit(b, 'undo', `Undid ${ing(l.ing).name.toLowerCase()}`) }
        return { undone: l ?? null }
      }
      case 'POST reset': Object.assign(b, fresh(ZONES.find((z) => z.id === b.id)!)); return { ok: true }
      case 'POST dismiss': b.fired.add(`${body.alert}_ok`); return { ok: true }
      case 'POST follow': b.follow = { video: videos[body.video_id], scale: body.scale }; emit(b, 'follow', `${b.name}: following “${videos[body.video_id].title}”`); return { ok: true }
      case 'DELETE follow': b.follow = null; return { ok: true }
    }
  }
  switch (`${method} ${path.split('?')[0]}`) {
    case 'POST /api/demo': reset(); return { demo: true }
    case 'GET /api/lab/options': return labSamples.options
    case 'GET /api/reference': return { recipes: [], fingerprint: {} }
    case 'POST /api/reference/import':
    case 'POST /api/adapt':
    case 'POST /api/cuts':
      return fail('This runs on your Mac (Python): open the dashboard from the Sous Chef AI server to use it')
    case 'POST /api/lab': {
      // The real Lab runs in Python on your Mac; the preview shows precomputed results.
      const src = body.source === 'lpg_small' ? 'lpg_large' : body.source
      const mode = body.mode === 'evaluate' ? 'upgrade' : body.mode
      const key = `${body.dish}:${body.dish === 'tadka' ? 'upgrade' : mode}:${src}` as keyof typeof labSamples.results
      const r = labSamples.results[key] as any
      if (!r) return fail('No precomputed example for that combination in the preview')
      return body.mode === 'evaluate' ? { ...r.before, preview: true } : { ...r, preview: true }
    }
    case 'GET /api/pantry': return mockPantry()
    case 'POST /api/profiles/active': active = body.id; emit(null, 'profile', `Cooking for ${prof().emoji} ${prof().name}`); return { active }
    case 'PUT /api/profiles': profiles = body.profiles; return mockPantry()
    case 'PUT /api/zones': return body
    case 'GET /api/videos': return Object.values(videos).map(({ id, title, channel, url }) => ({ id, title, channel, url, thumbnail: '' }))
    case 'POST /api/video/parse': return { ...COOKIES, title: `${COOKIES.title} (preview: sample recipe)` }
    case 'POST /api/calibrate/baseline': return fail('Needs the phone camera; not available in the preview')
    case 'POST /api/camera/command': return fail('No phone connected in the preview')
    case 'GET /api/history':
      return {
        sessions: [
          { id: 3, burner_name: 'Back left', dish: 'Dal', confidence: 0.8, overridden: 0, started_at: now() - 86400, ended_at: now() - 84600, cook_seconds: 1520, target_seconds: 1500, stirs: 6, alerts: '' },
          { id: 2, burner_name: 'Back right', dish: 'Chai', confidence: 0.9, overridden: 0, started_at: now() - 90000, ended_at: now() - 89500, cook_seconds: 410, target_seconds: 420, stirs: 2, alerts: 'target' },
          { id: 1, burner_name: 'Front right', dish: 'Rice', confidence: 0.75, overridden: 1, started_at: now() - 170000, ended_at: now() - 168800, cook_seconds: 1130, target_seconds: 1080, stirs: 1, alerts: 'target,unattended' },
        ],
        stats: [
          { dish: 'Dal', sessions: 9, total_seconds: 13500, avg_seconds: 1500 },
          { dish: 'Chai', sessions: 21, total_seconds: 8400, avg_seconds: 400 },
          { dish: 'Rice', sessions: 7, total_seconds: 7700, avg_seconds: 1100 },
        ],
      }
  }
  const v = /^\/api\/video\/([\w-]+)$/.exec(path)
  if (v && method === 'GET') return videos[v[1]] ?? COOKIES
  if (v && method === 'PUT') { videos[body.id ?? v[1]] = { ...(videos[v[1]] ?? COOKIES), ...body, id: v[1] }; return videos[v[1]] }
  return fail('Not available in the preview')
}
