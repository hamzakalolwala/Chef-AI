import type { Burner, Status } from './types'

export const clock = (seconds: number) => {
  const s = Math.max(0, Math.floor(seconds))
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const ss = String(s % 60).padStart(2, '0')
  return h ? `${h}:${String(m).padStart(2, '0')}:${ss}` : `${String(m).padStart(2, '0')}:${ss}`
}

export const minutes = (seconds: number | null | undefined) =>
  seconds == null ? '—' : seconds >= 3600 ? `${(seconds / 3600).toFixed(1)} h` : `${Math.round(seconds / 60)} min`

export const ago = (seconds: number) =>
  seconds < 60 ? `${Math.round(seconds)}s ago` : `${Math.round(seconds / 60)}m ago`

export const STATUS_LABEL: Record<Status, string> = {
  idle: 'Idle',
  ready: 'Pot on, flame off',
  cooking: 'Cooking',
  paused: 'Flame off',
  overdue: 'Past target',
  danger: 'Empty & lit!',
}

/** Progress-ring colour: teal → saffron → red as the dish approaches / passes its target. */
export function progressColor(b: Burner): string {
  if (b.status === 'danger') return '#ff3b3b'
  const p = b.session?.progress
  if (p == null) return b.flame.on ? '#5ec8ff' : '#5b6170'
  if (p >= 1) return '#ff5a4f'
  if (p >= 0.75) return '#ffb347'
  return '#3ee0c0'
}
