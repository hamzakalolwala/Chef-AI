import { CameraControls, ContactShadows, Environment, Lightformer, RoundedBox, Sparkles } from '@react-three/drei'
import { Canvas, useFrame } from '@react-three/fiber'
import { Bloom, EffectComposer, Vignette } from '@react-three/postprocessing'
import { type ComponentRef, useEffect, useMemo, useRef } from 'react'
import * as THREE from 'three'
import type { Burner, Zone } from '../lib/types'
import { BurnerUnit, type SprinkleCue } from './BurnerUnit'
import { materials } from './Vessel'

const W = 6.4 // stovetop width  (camera x)
const D = 4.2 // stovetop depth  (camera y)
const H = 0.32
// ?fx=0 disables bloom/vignette (for slower machines)
const QS = new URLSearchParams(location.search)
const FX = QS.get('fx') !== '0'

/** Map a burner's zone in the phone image onto the 3D stovetop. Image top = back of the stove. */
function layout(zone: Zone): { x: number; z: number; r: number } {
  const cx = zone.x + zone.w / 2
  const cy = zone.y + zone.h / 2
  const r = THREE.MathUtils.clamp(Math.min(zone.w * W, zone.h * D) * 0.33, 0.42, 0.82)
  return { x: (cx - 0.5) * W * 0.95, z: (cy - 0.5) * D * 0.95, r }
}

function tileTexture() {
  const c = document.createElement('canvas')
  c.width = c.height = 256
  const g = c.getContext('2d')!
  g.fillStyle = '#16181d'
  g.fillRect(0, 0, 256, 256)
  g.strokeStyle = '#0b0c0f'
  g.lineWidth = 6
  for (let i = 0; i <= 256; i += 64) {
    g.beginPath(); g.moveTo(i, 0); g.lineTo(i, 256); g.stroke()
    g.beginPath(); g.moveTo(0, i); g.lineTo(256, i); g.stroke()
  }
  const t = new THREE.CanvasTexture(c)
  t.wrapS = t.wrapT = THREE.RepeatWrapping
  t.repeat.set(8, 3)
  t.colorSpace = THREE.SRGBColorSpace
  return t
}

function Room() {
  const tiles = useMemo(tileTexture, [])
  return (
    <group>
      <mesh position={[0, -0.12, 0.6]} receiveShadow>
        <boxGeometry args={[18, 0.24, 9]} />
        <meshStandardMaterial color="#1d1a17" roughness={0.45} metalness={0.1} />
      </mesh>
      <mesh position={[0, 2.8, -3.4]}>
        <planeGeometry args={[18, 6]} />
        <meshStandardMaterial map={tiles} roughness={0.35} metalness={0.2} />
      </mesh>
      {/* warm under-cabinet light strip */}
      <mesh position={[0, 4.2, -3.35]}>
        <boxGeometry args={[14, 0.05, 0.05]} />
        <meshBasicMaterial color={new THREE.Color('#ffb36b').multiplyScalar(3)} toneMapped={false} />
      </mesh>
    </group>
  )
}

function Knob({ x, on }: { x: number; on: boolean }) {
  const knob = useRef<THREE.Group>(null)
  const led = useRef<THREE.MeshBasicMaterial>(null)
  useFrame((_, dt) => {
    if (knob.current) knob.current.rotation.z = THREE.MathUtils.lerp(knob.current.rotation.z, on ? -1.9 : 0, Math.min(1, dt * 6))
    if (led.current) led.current.color.lerp(new THREE.Color(on ? '#ff8a2a' : '#2a1b10').multiplyScalar(on ? 4 : 1), Math.min(1, dt * 6))
  })
  return (
    <group position={[x, H / 2, D / 2 + 0.24]}>
      <group ref={knob}>
        <mesh rotation-x={Math.PI / 2}>
          <cylinderGeometry args={[0.13, 0.14, 0.12, 32]} />
          <meshStandardMaterial {...materials.steel} roughness={0.35} />
        </mesh>
        <mesh position={[0, 0.07, 0.065]}>
          <boxGeometry args={[0.025, 0.08, 0.01]} />
          <meshBasicMaterial color="#111" />
        </mesh>
      </group>
      <mesh position={[0, -0.12, 0.01]}>
        <boxGeometry args={[0.1, 0.012, 0.01]} />
        <meshBasicMaterial ref={led} toneMapped={false} />
      </mesh>
    </group>
  )
}

function Stove({ burners, selected, onSelect, sprinkles }: { burners: Burner[]; selected: string | null; onSelect: (id: string | null) => void; sprinkles: Record<string, SprinkleCue> }) {
  const placed = burners.map((b) => ({ b, ...layout(b.zone) }))
  const knobs = [...placed].sort((a, c) => a.x - c.x)
  return (
    <group>
      <RoundedBox args={[W + 0.4, H, D + 0.4]} radius={0.06} position-y={H / 2} castShadow receiveShadow>
        <meshStandardMaterial color="#2b2e34" metalness={0.85} roughness={0.35} />
      </RoundedBox>
      <RoundedBox args={[W + 0.2, 0.03, D + 0.2]} radius={0.012} position-y={H + 0.012} receiveShadow>
        <meshPhysicalMaterial color="#050608" metalness={0.2} roughness={0.06} clearcoat={1} clearcoatRoughness={0.04} />
      </RoundedBox>
      {knobs.map(({ b }, i) => (
        <Knob key={b.id} x={(i - (knobs.length - 1) / 2) * Math.min(1.1, (W - 0.8) / Math.max(1, knobs.length))} on={b.flame.on} />
      ))}
      <group position-y={H + 0.03}>
        {placed.map(({ b, x, z, r }) => (
          <BurnerUnit key={b.id} b={b} position={[x, 0, z]} r={r} selected={selected === b.id} onSelect={onSelect} sprinkle={sprinkles[b.id]} />
        ))}
      </group>
    </group>
  )
}

/** Fly the camera to the selected burner; drift slowly when idle. */
function CameraRig({ burners, selected }: { burners: Burner[]; selected: string | null }) {
  const controls = useRef<ComponentRef<typeof CameraControls>>(null)
  const lastInput = useRef(performance.now())
  useEffect(() => {
    const c = controls.current
    if (!c) return
    const b = burners.find((x) => x.id === selected)
    // Shift the framing left so the stove isn't hidden under the burner sidebar.
    const offset = window.innerWidth > 900 ? 1 : 0
    if (b) {
      const { x, z } = layout(b.zone)
      c.setLookAt(x * 0.6, 4.6, z + 5.4, x, 0.4, z, true)
      c.setFocalOffset(offset * 0.9, 0, 0, true)
    } else if (window.innerWidth < 600) {
      // phone: cards cover the bottom half, so look from higher up and push the stove toward the top
      c.setLookAt(0, 15, 9.5, 0, 0, 0.6, true)
      c.setFocalOffset(0, 1.7, 0, true)
    } else {
      c.setLookAt(0, 7.4, 9.2, 0, 0, 0.3, true)
      c.setFocalOffset(offset * 1.7, 0.3, 0, true)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected])
  useEffect(() => {
    const c = controls.current
    if (!c) return
    const mark = () => (lastInput.current = performance.now())
    c.addEventListener('controlstart', mark)
    return () => c.removeEventListener('controlstart', mark)
  }, [])
  useFrame((st, dt) => {
    const c = controls.current
    if (!c || selected || performance.now() - lastInput.current < 10000) return
    c.azimuthAngle = THREE.MathUtils.lerp(c.azimuthAngle, Math.sin(st.clock.elapsedTime * 0.08) * 0.35, dt * 0.5)
  })
  return (
    <CameraControls
      ref={controls}
      minDistance={2.5}
      maxDistance={16}
      minPolarAngle={0.15}
      maxPolarAngle={Math.PI * 0.46}
      smoothTime={0.6}
    />
  )
}

export function Kitchen({ burners, selected, onSelect, sprinkles = {} }: { burners: Burner[]; selected: string | null; onSelect: (id: string | null) => void; sprinkles?: Record<string, SprinkleCue> }) {
  const anyFlame = burners.some((b) => b.flame.on)
  return (
    <Canvas
      shadows
      dpr={[1, 2]}
      camera={{ position: [0, 7.4, 9.2], fov: 36 }}
      gl={{ antialias: true, toneMapping: THREE.ACESFilmicToneMapping }}
      onPointerMissed={() => onSelect(null)}
    >
      <color attach="background" args={['#07080b']} />
      <fog attach="fog" args={['#07080b', 13, 28]} />
      <ambientLight intensity={0.12} />
      <spotLight position={[0, 8.5, 2.5]} angle={0.55} penumbra={0.9} intensity={110} color="#ffe3c2" castShadow shadow-mapSize={[2048, 2048]} shadow-bias={-0.0004} />
      <pointLight position={[-6, 3, 4]} intensity={8} color="#6f8cff" />
      <Environment resolution={256} frames={1}>
        <Lightformer form="rect" intensity={2.2} position={[0, 5, -6]} scale={[12, 3, 1]} color="#ffd6a8" />
        <Lightformer form="rect" intensity={1.1} position={[-7, 3, 1]} rotation-y={Math.PI / 2} scale={[8, 2, 1]} color="#9cb7ff" />
        <Lightformer form="rect" intensity={1.1} position={[7, 3, 1]} rotation-y={-Math.PI / 2} scale={[8, 2, 1]} color="#ffc9a0" />
        <Lightformer form="ring" intensity={1.2} position={[3, 7, 5]} scale={2.5} />
      </Environment>
      <Room />
      <Stove burners={burners} selected={selected} onSelect={onSelect} sprinkles={sprinkles} />
      <ContactShadows position={[0, 0.001, 0]} opacity={0.6} scale={14} blur={2.6} far={3} />
      <Sparkles count={70} scale={[12, 5, 8]} position={[0, 2.5, 0]} size={1.6} speed={0.25} opacity={anyFlame ? 0.35 : 0.15} color="#ffcf9a" />
      <CameraRig burners={burners} selected={selected} />
      {/* multisampling must stay 0: MSAA + mipmap bloom renders a black frame (three r187 / postprocessing 6.39).
          Retina's 2× pixel ratio keeps edges smooth anyway. */}
      {FX && (
      <EffectComposer multisampling={0}>
        <Bloom mipmapBlur luminanceThreshold={1.05} luminanceSmoothing={0.2} intensity={1.15} radius={0.7} />
        <Vignette offset={0.22} darkness={0.78} />
      </EffectComposer>
      )}
    </Canvas>
  )
}
