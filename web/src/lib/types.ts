export type Zone = { x: number; y: number; w: number; h: number }

export type Vessel = 'pot' | 'pan' | 'kadhai' | 'tawa' | 'cooker'

export type Status = 'idle' | 'ready' | 'cooking' | 'paused' | 'overdue' | 'danger'

export type Session = {
  started_at: number
  cook_seconds: number
  target_seconds: number | null
  progress: number | null
  dish_id: string | null
  dish: string | null
  vessel: Vessel
  color: string
  confidence: number
  overridden: boolean
  stirs: number
  since_attention: number
  flame_off_for: number | null
  alerts: string[]
  batch: number
  ingredients: IngredientRow[]
  follow: FollowState | null
  tongue?: Tongue | null
}

export type TasteChannel = 'salty' | 'sweet' | 'bitter' | 'sour' | 'umami' | 'heat' | 'fat'
export type Tongue = {
  intensity: { now: Record<TasteChannel, number>; ideal: Partial<Record<TasteChannel, number>> } | null
  family: { id: string; name: string; emoji: string; liking: number; complaint: string | null; active: boolean }[]
}

export type FollowStep = {
  ingredient: string | null
  name: string
  time: number | null
  target: number | null
  added: number
  done: boolean
  to_taste: boolean
}
export type FollowState = { id: string; title: string; url: string; scale: number; steps: FollowStep[]; next: FollowStep | null }

export type VideoItem = {
  ingredient: string | null
  name: string
  grams: number | null
  to_taste: boolean
  time: number | null
  source: string
  lines: string[]
}
export type VideoRecipe = {
  id: string
  url: string
  title: string
  channel?: string
  thumbnail?: string
  duration?: number
  servings: number | null
  caption_source: string | null
  items: VideoItem[]
  edited?: boolean
}

export type IngredientRow = {
  id: string
  name: string
  color: string
  grams: number
  target: number | null
  limit: number | null
  state: 'under' | 'ok' | 'over' | 'untracked'
}

export type Ingredient = { id: string; name: string; density: number; marker: number | null; color: string }
export type Spoon = { id: string; name: string; ml: number; marker: number | null }
export type Profile = {
  id: string
  name: string
  emoji: string
  multipliers: Record<string, number>
  tolerance: number
  fill: number
}
export type Pantry = {
  ingredients: Ingredient[]
  spoons: Spoon[]
  recipes: Record<string, Record<string, number>>
  profiles: Profile[]
  active_profile: string
}

export type Burner = {
  id: string
  name: string
  zone: Zone
  status: Status
  flame: { on: boolean; score: number; manual: boolean | null }
  motion: number
  steam: number
  occupied: number | null
  lid: number
  top: { id: string; name: string; p: number }[]
  pending_follow: string | null
  session: Session | null
}

export type ClassifierInfo = { name: string; ready: boolean; loading: boolean; samples: Record<string, number> }

export type KitchenState = {
  type: 'state'
  ts: number
  burners: Burner[]
  camera: { connected: boolean; streaming: boolean; fps: number; last_frame_at: number | null; devices: string[]; fogged?: boolean; clarity?: number; phone?: PhoneStatus | null }
  demo: boolean
  classifier: ClassifierInfo
  profile: Profile
}

export type KitchenEvent = {
  id: number
  ts: number
  burner_id: string | null
  kind: string
  level: 'info' | 'warn' | 'danger' | 'success'
  message: string
  ingredient?: string
  grams?: number
}

export type Dish = { id: string; name: string; minutes: number; vessel: Vessel; color: string }

export type ServerInfo = {
  lan_ip: string
  port: number
  camera_ws: string
  dashboard_url: string
  classifier: ClassifierInfo
  demo: boolean
}

export type HistoryRow = {
  id: number
  burner_name: string
  dish: string | null
  confidence: number | null
  overridden: number
  started_at: number
  ended_at: number
  cook_seconds: number
  target_seconds: number | null
  stirs: number
  alerts: string
}

export type PhoneStatus = { battery: number | null; charging: boolean | null; paused: boolean; fps: number; torch: boolean }
