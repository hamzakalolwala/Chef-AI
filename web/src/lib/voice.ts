import type { KitchenEvent } from './types'

const SPOKEN = new Set(['target', 'unattended', 'empty_flame', 'too_much', 'careful', 'forgot', 'ingredient_ok', 'mixup', 'check_spoon'])

/** Speak important alerts out loud and raise a system notification if the tab is hidden. */
export function announce(ev: KitchenEvent, voice: boolean) {
  if (!SPOKEN.has(ev.kind)) return
  if (voice && 'speechSynthesis' in window) {
    const u = new SpeechSynthesisUtterance(ev.message.replace('—', ','))
    u.rate = 1.02
    if (ev.level === 'danger') u.pitch = 1.15
    window.speechSynthesis.speak(u)
  }
  if (document.hidden && 'Notification' in window && Notification.permission === 'granted') {
    new Notification(ev.level === 'danger' ? '⚠️ Tadka' : '🍳 Tadka', { body: ev.message, tag: `${ev.burner_id}-${ev.kind}` })
  }
}

export function chime(level: KitchenEvent['level']) {
  try {
    const ctx = new AudioContext()
    const notes = level === 'danger' ? [880, 660, 880, 660] : level === 'warn' ? [660, 520] : [523, 659, 784]
    notes.forEach((f, i) => {
      const o = ctx.createOscillator()
      const g = ctx.createGain()
      o.frequency.value = f
      o.type = 'sine'
      const t = ctx.currentTime + i * 0.16
      g.gain.setValueAtTime(0.0001, t)
      g.gain.exponentialRampToValueAtTime(0.18, t + 0.02)
      g.gain.exponentialRampToValueAtTime(0.0001, t + 0.15)
      o.connect(g).connect(ctx.destination)
      o.start(t)
      o.stop(t + 0.16)
    })
    setTimeout(() => ctx.close(), 1200)
  } catch {
    /* audio blocked until the user interacts with the page */
  }
}
