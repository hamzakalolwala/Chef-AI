// Small GLSL programs used by the scene. All are additive / HDR so the bloom pass picks them up.

export const flameVertex = /* glsl */ `
  uniform float uTime;
  uniform float uLevel;
  attribute float aSeed;
  varying vec2 vUv;
  varying float vSeed;
  void main() {
    vUv = uv;
    vSeed = aSeed;
    vec3 p = position;
    float flicker = 0.78 + 0.22 * sin(uTime * 19.0 + aSeed * 31.0) * sin(uTime * 7.3 + aSeed * 11.0);
    p.y *= uLevel * flicker;
    p.xz *= 0.55 + 0.45 * uLevel;
    gl_Position = projectionMatrix * modelViewMatrix * instanceMatrix * vec4(p, 1.0);
  }
`

export const flameFragment = /* glsl */ `
  uniform float uLevel;
  varying vec2 vUv;
  varying float vSeed;
  void main() {
    float h = vUv.y;                       // 0 at the burner, 1 at the tip
    vec3 inner = vec3(0.45, 0.85, 3.2);
    vec3 outer = vec3(0.18, 0.22, 1.9);
    vec3 col = mix(inner, outer, smoothstep(0.0, 0.7, h));
    col += vec3(1.6, 0.6, 0.1) * smoothstep(0.82, 1.0, h) * 0.35 * fract(vSeed * 13.0);
    float a = pow(1.0 - h, 0.65) * uLevel;
    gl_FragColor = vec4(col * a, a);
  }
`

export const steamVertex = /* glsl */ `
  uniform float uTime;
  uniform float uHeight;
  uniform float uRadius;
  uniform float uIntensity;
  attribute float aSeed;
  varying float vAlpha;
  void main() {
    float life = fract(uTime * (0.08 + 0.1 * aSeed) + aSeed * 7.13);
    float ang = aSeed * 81.7;
    float rad = uRadius * (0.15 + 0.75 * fract(aSeed * 91.7));
    vec3 p = vec3(cos(ang) * rad, life * uHeight, sin(ang) * rad);
    p.x += sin(uTime * 0.9 + aSeed * 20.0) * 0.25 * life;
    p.z += cos(uTime * 0.7 + aSeed * 17.0) * 0.25 * life;
    vAlpha = smoothstep(0.0, 0.18, life) * (1.0 - life) * uIntensity;
    vec4 mv = modelViewMatrix * vec4(p, 1.0);
    gl_PointSize = (70.0 + 260.0 * life) * (3.0 / -mv.z);
    gl_Position = projectionMatrix * mv;
  }
`

export const steamFragment = /* glsl */ `
  varying float vAlpha;
  void main() {
    float d = length(gl_PointCoord - 0.5);
    float a = smoothstep(0.5, 0.0, d) * vAlpha * 0.22;
    gl_FragColor = vec4(vec3(0.92, 0.94, 0.98), a);
  }
`

export const ringVertex = /* glsl */ `
  varying vec2 vP;
  void main() {
    vP = position.xy;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`

export const ringFragment = /* glsl */ `
  uniform float uProgress;   // 0..1+ ; <0 means "no target" (show a spinning comet)
  uniform vec3 uColor;
  uniform float uTime;
  uniform float uActive;
  uniform float uSelected;
  varying vec2 vP;
  void main() {
    float a = atan(vP.x, vP.y);
    float t = (a < 0.0 ? a + 6.2831853 : a) / 6.2831853;
    float on;
    if (uProgress < 0.0) {
      float head = fract(uTime * 0.25);
      float d = fract(head - t);
      on = smoothstep(0.35, 0.0, d);
    } else {
      on = step(t, uProgress);
    }
    float pulse = uProgress >= 1.0 ? 0.55 + 0.45 * sin(uTime * 5.0) : 1.0;
    vec3 col = mix(vec3(0.05, 0.06, 0.08), uColor * (2.2 + uSelected) * pulse, on * uActive);
    float alpha = mix(0.55, 1.0, on) * (0.35 + 0.65 * uActive);
    gl_FragColor = vec4(col, alpha);
  }
`
