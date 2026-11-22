import { useFrame } from '@react-three/fiber'
import { useLayoutEffect, useMemo, useRef } from 'react'
import * as THREE from 'three'
import { flameFragment, flameVertex, ringFragment, ringVertex, steamFragment, steamVertex } from './shaders'

const lerp = THREE.MathUtils.lerp

/** Ring of instanced blue gas-flame jets. `level` 0..1 eases in/out. */
export function Flame({ radius, level, jets = 30 }: { radius: number; level: number; jets?: number }) {
  const mesh = useRef<THREE.InstancedMesh>(null)
  const light = useRef<THREE.PointLight>(null)
  const geometry = useMemo(() => {
    const g = new THREE.ConeGeometry(0.032, 0.2, 8, 1, true)
    g.translate(0, 0.1, 0) // base at y=0 so scaling grows upwards
    const seeds = new Float32Array(jets).map(() => Math.random())
    g.setAttribute('aSeed', new THREE.InstancedBufferAttribute(seeds, 1))
    return g
  }, [jets])
  const material = useMemo(
    () =>
      new THREE.ShaderMaterial({
        vertexShader: flameVertex,
        fragmentShader: flameFragment,
        uniforms: { uTime: { value: 0 }, uLevel: { value: 0 } },
        transparent: true,
        depthWrite: false,
        blending: THREE.AdditiveBlending,
        side: THREE.DoubleSide,
      }),
    [],
  )

  useLayoutEffect(() => {
    const o = new THREE.Object3D()
    for (let i = 0; i < jets; i++) {
      const a = (i / jets) * Math.PI * 2
      o.position.set(Math.cos(a) * radius, 0, Math.sin(a) * radius)
      o.rotation.set(0, -a, 0)
      o.rotateZ(-0.55) // lean outward like real burner ports
      o.updateMatrix()
      mesh.current!.setMatrixAt(i, o.matrix)
    }
    mesh.current!.instanceMatrix.needsUpdate = true
  }, [jets, radius])

  useFrame((s, dt) => {
    const u = material.uniforms
    u.uTime.value = s.clock.elapsedTime
    u.uLevel.value = lerp(u.uLevel.value, level, Math.min(1, dt * 4))
    if (light.current) {
      light.current.intensity = u.uLevel.value * (1.1 + Math.sin(s.clock.elapsedTime * 23) * 0.15)
    }
  })

  return (
    <group>
      <instancedMesh ref={mesh} args={[geometry, material, jets]} frustumCulled={false} />
      <pointLight ref={light} color="#5b8cff" distance={1.1} decay={2} position={[0, 0.05, 0]} />
    </group>
  )
}

/** GPU steam: particles rise and drift entirely in the vertex shader. */
export function Steam({ radius, height = 2.2, intensity, count = 70 }: {
  radius: number
  height?: number
  intensity: number
  count?: number
}) {
  const geometry = useMemo(() => {
    const g = new THREE.BufferGeometry()
    g.setAttribute('position', new THREE.BufferAttribute(new Float32Array(count * 3), 3))
    g.setAttribute('aSeed', new THREE.BufferAttribute(new Float32Array(count).map(() => Math.random()), 1))
    return g
  }, [count])
  const material = useMemo(
    () =>
      new THREE.ShaderMaterial({
        vertexShader: steamVertex,
        fragmentShader: steamFragment,
        uniforms: {
          uTime: { value: 0 },
          uHeight: { value: height },
          uRadius: { value: radius },
          uIntensity: { value: 0 },
        },
        transparent: true,
        depthWrite: false,
      }),
    [height, radius],
  )
  useFrame((s, dt) => {
    material.uniforms.uTime.value = s.clock.elapsedTime
    material.uniforms.uIntensity.value = lerp(material.uniforms.uIntensity.value, intensity, Math.min(1, dt * 1.5))
  })
  return <points geometry={geometry} material={material} frustumCulled={false} />
}

/** Flat ring on the stovetop showing cook progress (or a comet sweep when there's no target). */
export function ProgressRing({ inner, outer, progress, color, active, selected }: {
  inner: number
  outer: number
  progress: number | null
  color: string
  active: boolean
  selected: boolean
}) {
  const material = useMemo(
    () =>
      new THREE.ShaderMaterial({
        vertexShader: ringVertex,
        fragmentShader: ringFragment,
        uniforms: {
          uProgress: { value: 0 },
          uColor: { value: new THREE.Color(color) },
          uTime: { value: 0 },
          uActive: { value: 0 },
          uSelected: { value: 0 },
        },
        transparent: true,
        depthWrite: false,
        toneMapped: false,
      }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  )
  const tmp = useMemo(() => new THREE.Color(), [])
  useFrame((s, dt) => {
    const u = material.uniforms
    u.uTime.value = s.clock.elapsedTime
    const target = progress == null ? -1 : Math.min(progress, 1.0001)
    u.uProgress.value = target < 0 || u.uProgress.value < 0 ? target : lerp(u.uProgress.value, target, Math.min(1, dt * 3))
    u.uColor.value.lerp(tmp.set(color), Math.min(1, dt * 3))
    u.uActive.value = lerp(u.uActive.value, active ? 1 : 0, Math.min(1, dt * 3))
    u.uSelected.value = lerp(u.uSelected.value, selected ? 1 : 0, Math.min(1, dt * 5))
  })
  return (
    <mesh rotation-x={-Math.PI / 2} position-y={0.004} material={material}>
      <ringGeometry args={[inner, outer, 96, 1]} />
    </mesh>
  )
}

/** A burst of coloured grains falling into the pot whenever an ingredient is added. */
export function Sprinkle({ trigger, color, radius }: { trigger: number; color: string; radius: number }) {
  const count = 90
  const start = useRef(-10)
  const last = useRef(trigger)
  const geometry = useMemo(() => {
    const g = new THREE.BufferGeometry()
    g.setAttribute('position', new THREE.BufferAttribute(new Float32Array(count * 3), 3))
    g.setAttribute('aSeed', new THREE.BufferAttribute(new Float32Array(count).map(() => Math.random()), 1))
    return g
  }, [])
  const material = useMemo(
    () =>
      new THREE.ShaderMaterial({
        uniforms: { uAge: { value: 10 }, uColor: { value: new THREE.Color(color) }, uRadius: { value: radius } },
        vertexShader: /* glsl */ `
          uniform float uAge; uniform float uRadius; attribute float aSeed; varying float vA;
          void main() {
            float t = max(0.0, uAge - aSeed * 0.35);
            float a = aSeed * 97.0;
            float r = uRadius * 0.25 * fract(aSeed * 31.7) + t * 0.25 * uRadius;
            vec3 p = vec3(cos(a) * r, 1.5 - t * t * 2.4 - t * 0.6, sin(a) * r);
            p.y = max(p.y, 0.25);
            vA = (1.0 - smoothstep(0.7, 1.2, t)) * step(0.0, uAge - aSeed * 0.35);
            vec4 mv = modelViewMatrix * vec4(p, 1.0);
            gl_PointSize = 9.0 * (4.0 / -mv.z);
            gl_Position = projectionMatrix * mv;
          }`,
        fragmentShader: /* glsl */ `
          uniform vec3 uColor; varying float vA;
          void main() { if (length(gl_PointCoord - 0.5) > 0.5) discard; gl_FragColor = vec4(uColor * 1.4, vA); }`,
        transparent: true,
        depthWrite: false,
      }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  )
  useFrame((s) => {
    if (trigger !== last.current) {
      last.current = trigger
      start.current = s.clock.elapsedTime
      material.uniforms.uColor.value.set(color)
    }
    material.uniforms.uAge.value = s.clock.elapsedTime - start.current
  })
  return <points geometry={geometry} material={material} frustumCulled={false} />
}
