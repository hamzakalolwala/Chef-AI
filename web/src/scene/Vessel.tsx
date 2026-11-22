import { useFrame } from '@react-three/fiber'
import { useMemo, useRef } from 'react'
import * as THREE from 'three'
import type { Vessel as VesselType } from '../lib/types'

const steel = { color: '#d9dce2', metalness: 0.95, roughness: 0.22 }
const iron = { color: '#26272b', metalness: 0.6, roughness: 0.55 }
const brass = { color: '#b48a4c', metalness: 1, roughness: 0.3 }
const handleMat = { color: '#141414', metalness: 0.1, roughness: 0.7 }

/** Height of the vessel's opening above its base, for placing steam. */
export function vesselTop(type: VesselType, R: number) {
  return { pot: 0.8 * R, pan: 0.45 * R, kadhai: 0.6 * R, tawa: 0.08, cooker: 1.25 * R }[type]
}

/** Small spheres rising and popping on the food surface while it cooks. */
function Bubbles({ radius, y, color, active }: { radius: number; y: number; color: string; active: boolean }) {
  const group = useRef<THREE.Group>(null)
  const seeds = useMemo(
    () => Array.from({ length: 9 }, () => ({ a: Math.random() * Math.PI * 2, r: Math.sqrt(Math.random()) * radius * 0.8, s: Math.random() })),
    [radius],
  )
  const c = useMemo(() => new THREE.Color(color).lerp(new THREE.Color('#ffffff'), 0.35), [color])
  useFrame((st) => {
    group.current?.children.forEach((m, i) => {
      const k = seeds[i]
      const life = (st.clock.elapsedTime * (0.5 + k.s) + k.s * 10) % 1
      const sc = active ? Math.sin(life * Math.PI) * 0.06 * radius : 0
      m.scale.setScalar(Math.max(0.0001, sc))
    })
  })
  return (
    <group ref={group} position-y={y + 0.004}>
      {seeds.map((k, i) => (
        <mesh key={i} position={[Math.cos(k.a) * k.r, 0, Math.sin(k.a) * k.r]}>
          <sphereGeometry args={[1, 10, 8]} />
          <meshStandardMaterial color={c} roughness={0.2} emissive={c} emissiveIntensity={0.15} />
        </mesh>
      ))}
    </group>
  )
}

function Food({ radius, y, color, cooking }: { radius: number; y: number; color: string; cooking: boolean }) {
  return (
    <group>
      <mesh rotation-x={-Math.PI / 2} position-y={y}>
        <circleGeometry args={[radius, 48]} />
        <meshStandardMaterial color={color} roughness={0.35} emissive={color} emissiveIntensity={0.18} />
      </mesh>
      <Bubbles radius={radius} y={y} color={color} active={cooking} />
    </group>
  )
}

function Lid({ R, y }: { R: number; y: number }) {
  return (
    <group position-y={y}>
      <mesh scale={[1, 0.28, 1]} castShadow>
        <sphereGeometry args={[R * 1.01, 48, 12, 0, Math.PI * 2, 0, Math.PI / 2]} />
        <meshPhysicalMaterial color="#cfd6de" metalness={0.2} roughness={0.05} transmission={0.6} thickness={0.1} transparent opacity={0.85} />
      </mesh>
      <mesh position-y={R * 0.3}>
        <cylinderGeometry args={[0.06, 0.08, 0.08, 16]} />
        <meshStandardMaterial {...handleMat} />
      </mesh>
    </group>
  )
}

function SideHandles({ R, y }: { R: number; y: number }) {
  return (
    <>
      {[-1, 1].map((s) => (
        <mesh key={s} position={[s * (R + 0.06), y, 0]} rotation={[0, s > 0 ? 0 : Math.PI, Math.PI / 2]}>
          <torusGeometry args={[0.09, 0.022, 10, 20, Math.PI]} />
          <meshStandardMaterial {...steel} />
        </mesh>
      ))}
    </>
  )
}

function LongHandle({ R, y, length = 1.0 }: { R: number; y: number; length?: number }) {
  return (
    <mesh position={[R + length * R * 0.5, y, 0]} rotation-z={0.12} castShadow>
      <boxGeometry args={[length * R, 0.05, 0.12]} />
      <meshStandardMaterial {...handleMat} />
    </mesh>
  )
}

function Walls({ R, h }: { R: number; h: number }) {
  return (
    <group>
      <mesh position-y={h / 2} castShadow>
        <cylinderGeometry args={[R, R * 0.96, h, 64, 1, true]} />
        <meshStandardMaterial {...steel} side={THREE.DoubleSide} />
      </mesh>
      <mesh rotation-x={-Math.PI / 2} position-y={0.005}>
        <circleGeometry args={[R * 0.96, 48]} />
        <meshStandardMaterial {...steel} />
      </mesh>
      <mesh rotation-x={Math.PI / 2} position-y={h}>
        <torusGeometry args={[R, 0.018, 8, 64]} />
        <meshStandardMaterial {...steel} />
      </mesh>
    </group>
  )
}

export function Vessel({ type, R, color, cooking, lid, steam }: {
  type: VesselType
  R: number
  color: string
  cooking: boolean
  lid: boolean
  steam: number
}) {
  const whistle = useRef<THREE.Group>(null)
  useFrame((s) => {
    if (whistle.current) whistle.current.position.y = 1.25 * R + 0.12 + (steam > 0.5 ? Math.abs(Math.sin(s.clock.elapsedTime * 9)) * 0.03 : 0)
  })

  switch (type) {
    case 'tawa':
      return (
        <group>
          <mesh position-y={0.03} castShadow receiveShadow>
            <cylinderGeometry args={[R * 1.12, R * 1.05, 0.05, 64]} />
            <meshStandardMaterial {...iron} />
          </mesh>
          <mesh position-y={0.065} castShadow>
            <cylinderGeometry args={[R * 0.78, R * 0.78, 0.02, 48]} />
            <meshStandardMaterial color={color} roughness={0.7} emissive={color} emissiveIntensity={0.12} />
          </mesh>
          <LongHandle R={R * 1.1} y={0.04} length={0.9} />
        </group>
      )
    case 'kadhai': {
      const a = R * 1.15
      const b = a * 0.5
      return (
        <group>
          <mesh position-y={b} scale={[1, 0.5, 1]} castShadow>
            <sphereGeometry args={[a, 64, 20, 0, Math.PI * 2, Math.PI / 2, Math.PI / 2]} />
            <meshStandardMaterial {...iron} side={THREE.DoubleSide} />
          </mesh>
          <mesh rotation-x={Math.PI / 2} position-y={b}>
            <torusGeometry args={[a, 0.022, 8, 64]} />
            <meshStandardMaterial {...iron} />
          </mesh>
          {!lid && <Food radius={a * 0.9} y={b * 0.62} color={color} cooking={cooking} />}
          <SideHandles R={a} y={b * 0.95} />
          {lid && <Lid R={a} y={b} />}
        </group>
      )
    }
    case 'cooker': {
      const h = 1.1 * R
      return (
        <group>
          <Walls R={R * 0.9} h={h} />
          <mesh position-y={h + 0.04} castShadow>
            <cylinderGeometry args={[R * 0.86, R * 0.92, 0.08, 48]} />
            <meshStandardMaterial {...steel} />
          </mesh>
          <mesh position-y={h + 0.1}>
            <cylinderGeometry args={[0.05, 0.05, 0.12, 12]} />
            <meshStandardMaterial {...steel} />
          </mesh>
          <group ref={whistle}>
            <mesh>
              <cylinderGeometry args={[0.05, 0.08, 0.12, 12]} />
              <meshStandardMaterial {...handleMat} />
            </mesh>
          </group>
          <LongHandle R={R * 0.9} y={h + 0.06} length={1.1} />
        </group>
      )
    }
    case 'pan': {
      const h = 0.45 * R
      return (
        <group>
          <Walls R={R} h={h} />
          {!lid && <Food radius={R * 0.95} y={h * 0.6} color={color} cooking={cooking} />}
          <LongHandle R={R} y={h * 0.85} />
          {lid && <Lid R={R} y={h} />}
        </group>
      )
    }
    default: {
      const h = 0.8 * R
      return (
        <group>
          <Walls R={R} h={h} />
          {!lid && <Food radius={R * 0.95} y={h * 0.68} color={color} cooking={cooking} />}
          <SideHandles R={R} y={h * 0.82} />
          {lid && <Lid R={R} y={h} />}
        </group>
      )
    }
  }
}

export const materials = { steel, iron, brass, handleMat }
