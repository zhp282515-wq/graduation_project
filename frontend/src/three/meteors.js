import * as THREE from 'three'

const VERTEX = `
  uniform vec2 uViewport;
  uniform vec2 uHead;
  uniform vec2 uDirection;
  uniform vec2 uSize;
  varying vec2 vUv;

  void main() {
    vUv = uv;
    vec2 normal = vec2(-uDirection.y, uDirection.x);
    vec2 pixel = uHead + uDirection * (uv.x - 1.0) * uSize.x
      + normal * (uv.y - 0.5) * uSize.y;
    // 保持像素宽度，旋转或缩放星图时不会把尾迹放大成光带。
    gl_Position = vec4(pixel / uViewport * 2.0 - 1.0, 0.999, 1.0);
  }
`

const FRAGMENT = `
  uniform float uOpacity;
  varying vec2 vUv;

  void main() {
    float across = vUv.y - 0.5;
    float width = mix(0.022, 0.075, pow(vUv.x, 0.7));
    float trail = exp(-pow(across / width, 2.0)) * pow(vUv.x, 1.8);
    float head = exp(-pow((vUv.x - 0.98) / 0.025, 2.0) - pow(across / 0.11, 2.0));
    vec3 color = mix(vec3(0.52, 0.65, 0.75), vec3(1.0, 0.94, 0.82), pow(vUv.x, 3.0));
    gl_FragColor = vec4(color, (trail * 0.65 + head * 0.65) * uOpacity);
  }
`

/** 单个可复用的背景流星；由星图的帧循环推进，不创建额外计时器或事件。 */
export function createMeteors({ lowPower = false } = {}) {
  const uniforms = {
    uViewport: { value: new THREE.Vector2(1, 1) },
    uHead: { value: new THREE.Vector2() },
    uDirection: { value: new THREE.Vector2() },
    uSize: { value: new THREE.Vector2() },
    uOpacity: { value: 0 },
  }
  const mesh = new THREE.Mesh(
    new THREE.PlaneGeometry(1, 1),
    new THREE.ShaderMaterial({
      uniforms,
      vertexShader: VERTEX,
      fragmentShader: FRAGMENT,
      transparent: true,
      depthTest: false,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
      toneMapped: false,
    }),
  )
  mesh.name = 'background-meteor'
  mesh.frustumCulled = false
  mesh.renderOrder = -10
  mesh.visible = false

  const start = new THREE.Vector2()
  let delay = 2.5 + Math.random() * 2.5
  let age = 0
  let duration = 1
  let distance = 0
  let tail = 0

  function nextDelay() {
    return (lowPower ? 10 : 7) + Math.random() * 8
  }

  function reset() {
    mesh.visible = false
    uniforms.uOpacity.value = 0
    age = 0
    delay = 2.5 + Math.random() * 2.5
  }

  function update(dt, width, height, { enabled = true, paused = false } = {}) {
    if (!enabled || width <= 0 || height <= 0) {
      // 减少动态效果时连同尾迹一起隐藏，重新启用后保留一段安静时间。
      if (mesh.visible) reset()
      return
    }
    if (mesh.visible && (uniforms.uViewport.value.x !== width || uniforms.uViewport.value.y !== height)) reset()
    uniforms.uViewport.value.set(width, height)

    if (!mesh.visible) {
      if (paused) return
      delay -= dt
      if (delay > 0) return
      const toLeft = Math.random() < 0.7
      const angle = (0.15 + Math.random() * 0.1) * Math.PI
      uniforms.uDirection.value.set(Math.cos(angle) * (toLeft ? -1 : 1), -Math.sin(angle))
      start.set(width * (toLeft ? 0.68 + Math.random() * 0.27 : 0.3 + Math.random() * 0.3), height * (0.74 + Math.random() * 0.2))
      duration = 0.95 + Math.random() * 0.5
      distance = Math.min(520, Math.max(180, width * (0.3 + Math.random() * 0.15)))
      tail = Math.min(190, Math.max(72, width * (0.1 + Math.random() * 0.06)))
      age = 0
      mesh.visible = true
    }

    age += dt
    const progress = age / duration
    if (progress >= 1) {
      mesh.visible = false
      uniforms.uOpacity.value = 0
      delay = nextDelay()
      return
    }
    uniforms.uHead.value.copy(start).addScaledVector(uniforms.uDirection.value, distance * progress)
    uniforms.uSize.value.set(tail * Math.min(1, age / 0.16), 12)
    const fadeIn = Math.min(1, progress / 0.12)
    const fadeOut = Math.min(1, (1 - progress) / 0.35)
    uniforms.uOpacity.value = Math.sin(fadeIn * Math.PI / 2) * fadeOut * 0.88
  }

  function dispose() {
    mesh.removeFromParent()
    mesh.geometry.dispose()
    mesh.material.dispose()
  }

  return {
    mesh,
    update,
    reset,
    dispose,
    getState: () => ({ active: mesh.visible, progress: mesh.visible ? age / duration : 0, nextIn: delay }),
  }
}
