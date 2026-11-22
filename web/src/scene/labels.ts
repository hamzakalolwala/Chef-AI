import { useFrame, useThree } from '@react-three/fiber'
import { type RefObject } from 'react'
import * as THREE from 'three'

/** Floating labels live in normal DOM (ui/LabelLayer) and are positioned here every frame by
 *  projecting a 3D anchor to screen space. Avoids drei <Html>'s extra React roots. */
export const labelEls = new Map<string, HTMLDivElement>()

const v = new THREE.Vector3()
const camPos = new THREE.Vector3()

/** below=true hangs the label under the anchor (used for front-row burners so it doesn't cover the back row). */
export function useLabelAnchor(id: string, anchor: RefObject<THREE.Object3D | null>, below = false) {
  const { camera, size } = useThree()
  useFrame(() => {
    const el = labelEls.get(id)
    const a = anchor.current
    if (!el || !a) return
    a.getWorldPosition(v)
    const dist = camPos.setFromMatrixPosition(camera.matrixWorld).distanceTo(v)
    v.project(camera)
    if (v.z > 1) {
      el.style.visibility = 'hidden'
      return
    }
    const x = ((v.x + 1) / 2) * size.width
    const y = ((1 - v.y) / 2) * size.height
    const scale = THREE.MathUtils.clamp(8.5 / dist, 0.75, 1.3)
    el.style.visibility = ''
    el.style.transform = `translate(${x}px, ${y}px) translate(-50%, ${below ? '0%' : '-100%'}) scale(${scale})`
    el.style.transformOrigin = below ? '50% 0%' : '50% 100%'
    el.style.zIndex = String(1000 - Math.round(dist * 10))
  })
}
