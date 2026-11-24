// Browser port of backend/app/tongue.py (used by the preview's simulated kitchen).
import type { TasteChannel } from './types'

export const CHANNELS: TasteChannel[] = ['salty', 'sweet', 'bitter', 'sour', 'umami', 'heat', 'fat']
const R: Record<TasteChannel, [number, number]> = {
  salty: [150, 1.4], sweet: [250, 1.3], bitter: [3, 1.5], sour: [8, 1.2], umami: [6, 1], heat: [30, 1], fat: [60, 1],
}
const W: Record<TasteChannel, number> = { salty: 1, sweet: 0.8, bitter: 0.7, sour: 0.5, umami: 0.3, heat: 0.8, fat: 0.4 }
const S: Record<TasteChannel, number> = { salty: 1.3, sweet: 1.6, bitter: 1.2, sour: 2, umami: 2.5, heat: 1.9, fat: 2.2 }
const WATER: Record<string, number> = { chai: 0.92, dal: 0.8, rice: 0.65, eggs: 0.75, curry: 0.75, sabzi: 0.8, poha: 0.55 }
const UMAMI: Record<string, number> = { curry: 3.5, dal: 1.5, eggs: 1, rice: 0.3, chai: 0.2 }

const hill = (c: number, k: number, n: number) => (c <= 0 ? 0 : (c / k) ** n / (1 + (c / k) ** n))

export function stimulus(g: Record<string, number>, mass: number, dish: string | null) {
  const water = (mass * (WATER[dish ?? ''] ?? (g.flour > 50 ? 0.3 : 0.75))) / 1000
  const kg = mass / 1000
  return {
    salty: (((g.salt ?? 0) / 58.44 + (g.baking_soda ?? 0) / 84) * 1000) / water,
    sweet: ((((g.sugar ?? 0) + 0.95 * (g.brown_sugar ?? 0) + 0.8 * (g.honey ?? 0)) / 342.3) * 1000) / water,
    heat: (((g.chili ?? 0) * 0.0015) / 305.4) * 1e6 / water,
    bitter: ((g.turmeric ?? 0) + 0.5 * (g.cocoa ?? 0) + 1.5 * (g.baking_soda ?? 0)) / kg,
    fat: ((g.oil ?? 0) + (g.ghee ?? 0) + 0.82 * (g.butter ?? 0) + 0.035 * (g.milk ?? 0)) / kg,
    sour: 0,
    umami: UMAMI[dish ?? ''] ?? 1,
  } as Record<TasteChannel, number>
}

export function perceive(s: Record<TasteChannel, number>) {
  const r = Object.fromEntries(CHANNELS.map((c) => [c, hill(s[c], R[c][0], R[c][1])])) as Record<TasteChannel, number>
  const o = { ...r }
  o.salty = Math.min(1, r.salty * (1 + 0.2 * r.umami))
  o.bitter = r.bitter * Math.max(0, 1 - 0.35 * r.sweet - 0.25 * r.salty)
  o.heat = r.heat * Math.max(0, 1 - 0.25 * r.fat - 0.15 * r.sweet)
  o.sour = r.sour * Math.max(0, 1 - 0.3 * r.sweet)
  return Object.fromEntries(CHANNELS.map((c) => [c, +(10 * o[c]).toFixed(2)])) as Record<TasteChannel, number>
}

export function liking(now: Record<TasteChannel, number>, ideal: Record<TasteChannel, number>): [number, string | null] {
  const parts: Partial<Record<TasteChannel, number>> = {}
  for (const c of CHANNELS) {
    if (c === 'bitter' || c === 'sour') {
      const ceil = Math.max(1.5, ideal[c] ?? 0)
      parts[c] = now[c] <= ceil ? 1 : Math.exp(-((now[c] - ceil) ** 2) / (2 * S[c] ** 2))
    } else if ((ideal[c] ?? 0) > 0.05) parts[c] = Math.exp(-((now[c] - ideal[c]) ** 2) / (2 * S[c] ** 2))
  }
  const ks = Object.keys(parts) as TasteChannel[]
  const wsum = ks.reduce((a, c) => a + W[c], 0)
  const geo = Math.exp(ks.reduce((a, c) => a + W[c] * Math.log(Math.max(parts[c]!, 1e-6)), 0) / wsum)
  const worst = ks.reduce((a, c) => (parts[c]! < parts[a]! ? c : a), ks[0])
  const score = +(10 * geo * Math.sqrt(parts[worst]!)).toFixed(1)
  if (parts[worst]! >= 0.75) return [score, null]
  const hi = now[worst] > (ideal[worst] || 1.5)
  const words: Record<TasteChannel, [string, string]> = {
    salty: ['too salty', 'needs salt'], sweet: ['too sweet', 'not sweet enough'], bitter: ['bitter', 'bitter'],
    sour: ['too sour', 'needs tang'], umami: ['too savoury', 'flat'], heat: ['too spicy', 'too mild'], fat: ['too oily', 'dry'],
  }
  return [score, words[worst][hi ? 0 : 1]]
}
