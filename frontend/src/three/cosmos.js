import * as THREE from 'three'

const SKY_VERTEX = `
  varying vec3 vDirection;
  void main() {
    vDirection = normalize(position);
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`

const SKY_FRAGMENT = `
  uniform mat3 uGalactic;
  varying vec3 vDirection;

  float hash(vec3 p) {
    p = fract(p * 0.3183099 + vec3(0.1, 0.2, 0.3));
    p *= 17.0;
    return fract(p.x * p.y * p.z * (p.x + p.y + p.z));
  }
  float noise(vec3 p) {
    vec3 i = floor(p);
    vec3 f = fract(p);
    f = f * f * (3.0 - 2.0 * f);
    return mix(
      mix(mix(hash(i), hash(i + vec3(1,0,0)), f.x),
          mix(hash(i + vec3(0,1,0)), hash(i + vec3(1,1,0)), f.x), f.y),
      mix(mix(hash(i + vec3(0,0,1)), hash(i + vec3(1,0,1)), f.x),
          mix(hash(i + vec3(0,1,1)), hash(i + vec3(1,1,1)), f.x), f.y), f.z);
  }
  float cloud(vec3 p) {
    float sum = 0.0;
    float weight = 0.56;
    for (int i = 0; i < CLOUD_OCTAVES; i++) {
      sum += noise(p) * weight;
      p = p * 2.08 + vec3(3.7, 1.9, 5.3);
      weight *= 0.48;
    }
    return sum;
  }
  void main() {
    vec3 d = normalize(vDirection);
    vec3 g = uGalactic * d;
    // 银河：一条窄带 + 一层散开的银河光，云气细、暗尘软，带外接近纯黑。
    float structure = cloud(g * 8.0);
    float latitude = g.y + (structure - 0.5) * 0.1;
    float wide = exp(-latitude * latitude * 22.0);
    float core = exp(-latitude * latitude * 80.0);
    float mist = cloud(g * 19.0 + structure * 2.0);
    float dust = smoothstep(0.32, 0.7, cloud(g * 26.0 + vec3(12.0)));
    float emission = (wide * 0.22 + core * 0.78) * (0.55 + mist * 0.75) * (1.0 - dust * 0.4);
    vec3 cold = vec3(0.030, 0.034, 0.044);
    vec3 warm = vec3(0.036, 0.036, 0.038);
    vec3 light = mix(cold, warm, smoothstep(0.3, 0.75, structure));
    vec3 color = vec3(0.0016, 0.0019, 0.0025) + light * emission * 0.38;
    gl_FragColor = vec4(color, 1.0);
    #include <tonemapping_fragment>
    #include <colorspace_fragment>
  }
`

const STAR_VERTEX = `
  attribute float aSize;
  attribute float aPhase;
  attribute float aBrightness;
  attribute vec3 aColor;
  uniform float uPixel;
  uniform float uTime;
  uniform float uPerspective;
  varying vec3 vColor;
  varying float vAlpha;
  varying float vSize;
  void main() {
    vec4 mv = modelViewMatrix * vec4(position, 1.0);
    float dist = max(1.0, -mv.z);
    float perspective = mix(1.0, clamp(650.0 / dist, 0.45, 2.5), uPerspective);
    // 背景星也只到几个像素：远看是星点，不是一片散开的光斑。
    float size = clamp(aSize * perspective, 1.0, 3.4);
    gl_PointSize = size * uPixel;
    vSize = gl_PointSize;
    vColor = aColor;
    vAlpha = aBrightness * 0.34 * (0.96 + 0.04 * sin(uTime * 0.35 + aPhase * 6.28318));
    vAlpha *= mix(1.0, smoothstep(25.0, 110.0, dist), uPerspective);
    gl_Position = projectionMatrix * mv;
  }
`

const STAR_FRAGMENT = `
  varying vec3 vColor;
  varying float vAlpha;
  varying float vSize;
  void main() {
    float radius = length(gl_PointCoord - 0.5);
    // 同样只留一个设备像素的抗锯齿边缘，圆外没有渐隐。
    float edge = clamp(1.0 / max(vSize, 1.0), 0.1, 0.34);
    float disc = 1.0 - smoothstep(0.5 - edge, 0.5, radius);
    if (disc < 0.004) discard;
    gl_FragColor = vec4(vColor, disc * vAlpha);
  }
`

/** 包围镜头的银河与远星、保持世界坐标的近星；均不参与知识节点索引和拾取。 */
export function createCosmos({ lowPower = false } = {}) {
  const group = new THREE.Group()
  group.name = 'cosmic-background'
  const galactic = new THREE.Matrix3().setFromMatrix4(
    new THREE.Matrix4().makeRotationFromEuler(new THREE.Euler(0.12, 0, -1)),
  )
  const inverseGalactic = galactic.clone().transpose()
  const sky = new THREE.Mesh(
    new THREE.SphereGeometry(6500, 32, 20),
    new THREE.ShaderMaterial({
      uniforms: { uGalactic: { value: galactic } },
      defines: { CLOUD_OCTAVES: lowPower ? 3 : 4 },
      vertexShader: SKY_VERTEX,
      fragmentShader: SKY_FRAGMENT,
      side: THREE.BackSide,
      depthTest: false,
      depthWrite: false,
    }),
  )
  sky.name = 'galactic-sky'
  sky.frustumCulled = false
  sky.renderOrder = -100
  group.add(sky)

  const starUniforms = { uPixel: { value: 1 }, uTime: { value: 0 } }
  const palette = [0xc8d9ff, 0xe9efff, 0xfff3dc, 0xe5e9f1, 0xffd5ac]
  const vector = new THREE.Vector3()

  function buildLayer(count, near = false) {
    const positions = new Float32Array(count * 3)
    const colors = new Float32Array(count * 3)
    const sizes = new Float32Array(count)
    const brightness = new Float32Array(count)
    const phases = new Float32Array(count)
    for (let i = 0; i < count; i += 1) {
      const theta = Math.random() * Math.PI * 2
      const radius = near ? 180 + Math.random() * 1250 : 3200 + Math.random() * 2000
      if (!near && i > count * 0.64) {
        // 银河方向星密度更高，垂直于银盘逐渐稀疏。
        const latitude = (Math.random() + Math.random() + Math.random() - 1.5) * 0.15
        vector.set(Math.cos(theta), latitude, Math.sin(theta)).normalize().applyMatrix3(inverseGalactic)
      } else {
        const z = Math.random() * 2 - 1
        const r = Math.sqrt(1 - z * z)
        vector.set(r * Math.cos(theta), z, r * Math.sin(theta))
      }
      vector.multiplyScalar(radius).toArray(positions, i * 3)
      const color = new THREE.Color(palette[Math.floor(Math.random() * palette.length)])
      color.toArray(colors, i * 3)
      const magnitude = Math.pow(Math.random(), 4)
      sizes[i] = (near ? 1.2 : 0.9) + magnitude * (near ? 2.1 : 3.0)
      brightness[i] = (near ? 0.18 : 0.14) + magnitude * (near ? 0.48 : 0.73)
      phases[i] = Math.random()
    }
    const geometry = new THREE.BufferGeometry()
    geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3))
    geometry.setAttribute('aColor', new THREE.BufferAttribute(colors, 3))
    geometry.setAttribute('aSize', new THREE.BufferAttribute(sizes, 1))
    geometry.setAttribute('aBrightness', new THREE.BufferAttribute(brightness, 1))
    geometry.setAttribute('aPhase', new THREE.BufferAttribute(phases, 1))
    const stars = new THREE.Points(geometry, new THREE.ShaderMaterial({
      uniforms: { ...starUniforms, uPerspective: { value: near ? 1 : 0 } },
      vertexShader: STAR_VERTEX,
      fragmentShader: STAR_FRAGMENT,
      transparent: true,
      depthWrite: false,
      depthTest: false,
      blending: THREE.AdditiveBlending,
    }))
    stars.name = near ? 'nearby-stars' : 'distant-stars'
    stars.frustumCulled = false
    stars.renderOrder = near ? -30 : -80
    group.add(stars)
    return stars
  }

  const distant = buildLayer(lowPower ? 6000 : 14000)
  const nearby = buildLayer(lowPower ? 240 : 520, true)
  let time = 0

  function update(camera, dt, pixelRatio, reducedMotion) {
    if (!reducedMotion) time += dt
    starUniforms.uPixel.value = pixelRatio
    starUniforms.uTime.value = time
    // 星空无穷远，只有近星随镜头的平移和穿行产生明显视差。
    sky.position.copy(camera.position)
    distant.position.copy(camera.position)
  }

  function dispose() {
    group.removeFromParent()
    group.traverse((child) => {
      child.geometry?.dispose()
      child.material?.dispose()
    })
  }

  return {
    group,
    update,
    dispose,
    getState: () => ({ distant: distant.geometry.getAttribute('position').count, nearby: nearby.geometry.getAttribute('position').count, time }),
  }
}
