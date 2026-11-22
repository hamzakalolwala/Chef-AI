import { useFrame } from '@react-three/fiber'
import { useRef, useState } from 'react'
import * as THREE from 'three'
import { progressColor } from '../lib/format'
import type { Burner } from '../lib/types'
import { Flame, ProgressRing, Sprinkle, Steam } from './Effects'
import { Vessel, materials, vesselTop } from './Vessel'
import { useLabelAnchor } from './labels'

const GRATE_Y = 0.17

function Grate({ r }: { r: number }) {
  return (
    <group>
      <mesh rotation-x={Math.PI / 2} position-y={GRATE_Y}>
        <torusGeometry args={[r * 0.98, 0.028, 8, 48]} />
        <meshStandardMaterial {...materials.iron} />
      </mesh>
      {[0, 1, 2, 3, 4].map((i) => {
        const a = (i / 5) * Math.PI * 2 + 0.3
        return (
          <group key={i} rotation-y={a}>
            <mesh position={[r * 0.62, GRATE_Y, 0]}>
              <boxGeometry args={[r * 0.72, 0.045, 0.05]} />
              <meshStandardMaterial {...materials.iron} />
            </mesh>
            <mesh position={[r * 0.98, GRATE_Y / 2, 0]}>
              <boxGeometry args={[0.05, GRATE_Y, 0.05]} />
              <meshStandardMaterial {...materials.iron} />
            </mesh>
          </group>
        )
      })}
    </group>
  )
}

export type SprinkleCue = { key: number; color: string }

export function BurnerUnit({ b, position, r, selected, onSelect, sprinkle }: {
  b: Burner
  sprinkle?: SprinkleCue
  position: [number, number, number]
  r: number
  selected: boolean
  onSelect: (id: string | null) => void
}) {
  const [hover, setHover] = useState(false)
  const vessel = useRef<THREE.Group>(null)
  const anchor = useRef<THREE.Group>(null)
  const frontRow = b.zone.y + b.zone.h / 2 > 0.5
  useLabelAnchor(b.id, anchor, frontRow)
  const s = b.session
  const showVessel = !!s || (b.occupied ?? 0) > 0.6
  const type = s?.vessel ?? 'pot'
  const R = r * 1.02
  const top = vesselTop(type, R)
  const flameLevel = b.flame.on ? Math.max(0.55, Math.min(1, b.flame.score || 0.85)) : 0
  const cooking = b.flame.on && !!s

  // A gentle settle when the pot appears, and a subtle wobble while stirring.
  useFrame((st, dt) => {
    if (!vessel.current) return
    const g = vessel.current
    const targetY = showVessel ? GRATE_Y + 0.03 : GRATE_Y + 1.2
    g.position.y = THREE.MathUtils.lerp(g.position.y, targetY, Math.min(1, dt * 5))
    const wobble = b.motion > 0.06 ? Math.sin(st.clock.elapsedTime * 14) * 0.02 : 0
    g.rotation.z = THREE.MathUtils.lerp(g.rotation.z, wobble, Math.min(1, dt * 8))
    const sc = showVessel ? 1 : 0.001
    g.scale.setScalar(THREE.MathUtils.lerp(g.scale.x, sc, Math.min(1, dt * 6)))
  })

  return (
    <group position={position}>
      <ProgressRing
        inner={r * 1.12}
        outer={r * 1.22}
        progress={s ? s.progress : null}
        color={progressColor(b)}
        active={!!s || hover || selected}
        selected={selected || hover}
      />
      {/* burner base + brass cap */}
      <mesh position-y={0.03} receiveShadow>
        <cylinderGeometry args={[r * 0.5, r * 0.56, 0.06, 40]} />
        <meshStandardMaterial color="#1b1c20" metalness={0.7} roughness={0.4} />
      </mesh>
      <mesh position-y={0.075} castShadow>
        <cylinderGeometry args={[r * 0.4, r * 0.44, 0.04, 40]} />
        <meshStandardMaterial {...materials.brass} />
      </mesh>
      <group position-y={0.07}>
        <Flame radius={r * 0.43} level={flameLevel} />
      </group>
      <Grate r={r} />
      <group ref={vessel} position-y={GRATE_Y + 1.2} scale={0.001}>
        <Vessel type={type} R={R} color={s?.color ?? '#c9a46a'} cooking={cooking} lid={b.lid > 0.5} steam={b.steam} />
        {type !== 'tawa' && <group position-y={top * 0.85}><Steam radius={R * 0.6} height={2.2} intensity={cooking ? Math.min(1, 0.25 + b.steam) : 0} /></group>}
      </group>
      {sprinkle && <group position-y={GRATE_Y + top * 0.6}><Sprinkle trigger={sprinkle.key} color={sprinkle.color} radius={R} /></group>}
      <group ref={anchor} position={frontRow ? [0, 0.05, r * 1.3] : [0, GRATE_Y + top + 0.55, 0]} />
      {/* invisible hit target */}
      <mesh
        position-y={0.4}
        visible={false}
        onClick={(e) => {
          e.stopPropagation()
          onSelect(selected ? null : b.id)
        }}
        onPointerOver={(e) => {
          e.stopPropagation()
          setHover(true)
          document.body.style.cursor = 'pointer'
        }}
        onPointerOut={() => {
          setHover(false)
          document.body.style.cursor = ''
        }}
      >
        <cylinderGeometry args={[r * 1.25, r * 1.25, 0.9, 24]} />
        <meshBasicMaterial />
      </mesh>
    </group>
  )
}
