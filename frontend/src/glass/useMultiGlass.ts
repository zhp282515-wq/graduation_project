import { onBeforeUnmount, onMounted, type Ref } from 'vue'
import { createFragmentShader, MAX_PANELS, VERTEX_SHADER } from './glass-multi'

export interface PanelSpec {
  /** 中心点（CSS 像素，相对 canvas 左上角） */
  x: number
  y: number
  /** 半宽 / 半高（CSS 像素） */
  w: number
  h: number
  radius: number
}

export interface MultiGlassOptions {
  canvas: Ref<HTMLCanvasElement | null>
  panels: Ref<PanelSpec[]>
  backgroundUrl: string
  tint?: [number, number, number]
  saturation?: number
  distortion?: number
  /** 磨砂强度：0 清晰，1 重度模糊 */
  blur?: number
  /** 乳白程度：0 全透明玻璃，1 几乎不透明 */
  frost?: number
  shadowIntensity?: number
  shadowBlur?: number
  glassMode?: 'light' | 'dark'
  chromaticAberration?: number
}

/** 用 2D canvas 对图片做降采样 + 高斯模糊，得到磨砂纹理 */
async function buildBlurTexture(url: string, blurPx: number) {
  const img = new Image()
  img.crossOrigin = 'anonymous'
  await new Promise<void>((resolve, reject) => {
    img.onload = () => resolve()
    img.onerror = () => reject(new Error(`背景图加载失败: ${url}`))
    img.src = url
  })

  // 先降采样，再让浏览器在放大时做平滑，模糊成本几乎为零
  const scale = 1.0
  const w = Math.max(2, Math.round(img.width * scale))
  const h = Math.max(2, Math.round(img.height * scale))

  const canvas = document.createElement('canvas')
  canvas.width = w
  canvas.height = h
  const ctx = canvas.getContext('2d')!
  ctx.filter = `blur(${Math.max(0.5, blurPx * scale)}px)`
  ctx.drawImage(img, 0, 0, w, h)

  return { image: canvas as TexImageSource, src: img, aspect: img.width / img.height }
}

export function useMultiGlass(o: MultiGlassOptions) {
  let gl: WebGLRenderingContext | null = null
  let program: WebGLProgram | null = null
  let sharpTex: WebGLTexture | null = null
  let blurTex: WebGLTexture | null = null
  let raf = 0
  let imageAspect = 1
  let lastSize = ''
  let disposed = false
  let loc: Record<string, WebGLUniformLocation | null> = {}

  const centerBuf = new Float32Array(MAX_PANELS * 2)
  const halfBuf = new Float32Array(MAX_PANELS * 2)
  const radiusBuf = new Float32Array(MAX_PANELS)

  const compile = (type: number, src: string) => {
    const s = gl!.createShader(type)!
    gl!.shaderSource(s, src)
    gl!.compileShader(s)
    if (!gl!.getShaderParameter(s, gl!.COMPILE_STATUS)) {
      console.error('shader error:', gl!.getShaderInfoLog(s))
      return null
    }
    return s
  }

  const makeTex = () => {
    const t = gl!.createTexture()!
    gl!.bindTexture(gl!.TEXTURE_2D, t)
    gl!.texParameteri(gl!.TEXTURE_2D, gl!.TEXTURE_WRAP_S, gl!.CLAMP_TO_EDGE)
    gl!.texParameteri(gl!.TEXTURE_2D, gl!.TEXTURE_WRAP_T, gl!.CLAMP_TO_EDGE)
    // 非 2 的幂纹理：用 LINEAR，不放 mipmap
    gl!.texParameteri(gl!.TEXTURE_2D, gl!.TEXTURE_MIN_FILTER, gl!.LINEAR)
    gl!.texParameteri(gl!.TEXTURE_2D, gl!.TEXTURE_MAG_FILTER, gl!.LINEAR)
    return t
  }

  const upload = (tex: WebGLTexture | null, src: TexImageSource) => {
    if (!gl || !tex) return
    gl.bindTexture(gl.TEXTURE_2D, tex)
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, src)
  }

  const white = () => {
    const c = document.createElement('canvas')
    c.width = c.height = 8
    const ctx = c.getContext('2d')!
    ctx.fillStyle = '#eef4ff'
    ctx.fillRect(0, 0, 8, 8)
    return c
  }

  const draw = () => {
    const el = o.canvas.value
    if (!el || !gl || !program || !sharpTex || !blurTex) return
    const dpr = window.devicePixelRatio || 1
    const size = `${el.clientWidth}x${el.clientHeight}`
    if (size !== lastSize) {
      el.width = Math.round(el.clientWidth * dpr)
      el.height = Math.round(el.clientHeight * dpr)
      gl.viewport(0, 0, el.width, el.height)
      lastSize = size
    }

    const panels = o.panels.value.slice(0, MAX_PANELS)
    centerBuf.fill(0)
    halfBuf.fill(0)
    radiusBuf.fill(0)
    let heightRef = 1
    panels.forEach((p, i) => {
      centerBuf[i * 2] = p.x * dpr
      // DOM 的 y 向下，WebGL 的 fragCoord y 向上 → 翻转
      centerBuf[i * 2 + 1] = el.height - p.y * dpr
      halfBuf[i * 2] = p.w * dpr
      halfBuf[i * 2 + 1] = p.h * dpr
      radiusBuf[i] = p.radius * dpr
      heightRef = Math.max(heightRef, p.h * dpr)
    })

    gl.useProgram(program)
    gl.uniform2f(loc.u_resolution, el.width, el.height)
    gl.uniform1i(loc.u_texture, 0)
    gl.uniform1i(loc.u_blurTex, 1)
    gl.uniform3f(loc.u_tint, ...(o.tint ?? [1, 1, 1]))
    gl.uniform1f(loc.u_saturation, o.saturation ?? 1.2)
    gl.uniform1f(loc.u_distortion, o.distortion ?? 1)
    gl.uniform1f(loc.u_imageAspect, imageAspect)
    gl.uniform1f(loc.u_canvasAspect, el.width / el.height)
    gl.uniform1f(loc.u_glassMode, o.glassMode === 'dark' ? 1 : 0)
    gl.uniform1f(loc.u_shadowIntensity, o.shadowIntensity ?? 0.55)
    gl.uniform2f(loc.u_shadowOffset, 0, -10 * dpr)
    gl.uniform1f(loc.u_shadowBlur, (o.shadowBlur ?? 34) * dpr)
    gl.uniform1f(loc.u_chromaticAberration, o.chromaticAberration ?? 0.35)
    gl.uniform1f(loc.u_heightRef, heightRef)
    gl.uniform1f(loc.u_frost, o.frost ?? 0.16)
    gl.uniform1f(loc.u_panelCount, panels.length)
    gl.uniform2fv(loc.u_panelCenter, centerBuf)
    gl.uniform2fv(loc.u_panelHalf, halfBuf)
    gl.uniform1fv(loc.u_panelRadius, radiusBuf)

    gl.activeTexture(gl.TEXTURE0)
    gl.bindTexture(gl.TEXTURE_2D, sharpTex)
    gl.activeTexture(gl.TEXTURE1)
    gl.bindTexture(gl.TEXTURE_2D, blurTex)
    gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4)
  }

  const loop = () => {
    if (disposed) return
    draw()
    raf = requestAnimationFrame(loop)
  }

  onMounted(async () => {
    const el = o.canvas.value
    if (!el) return
    gl = el.getContext('webgl')
    if (!gl) return console.error('WebGL not supported')

    const hasD = !!gl.getExtension('OES_standard_derivatives')
    const vs = compile(gl.VERTEX_SHADER, VERTEX_SHADER)
    const fs = compile(gl.FRAGMENT_SHADER, createFragmentShader(hasD))
    if (!vs || !fs) return
    program = gl.createProgram()!
    gl.attachShader(program, vs)
    gl.attachShader(program, fs)
    gl.linkProgram(program)
    if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
      console.error('link error:', gl.getProgramInfoLog(program))
      return
    }
    for (const n of ['u_resolution','u_texture','u_blurTex','u_tint','u_saturation','u_distortion',
      'u_imageAspect','u_canvasAspect','u_glassMode','u_shadowIntensity','u_shadowOffset','u_shadowBlur',
      'u_chromaticAberration','u_heightRef','u_frost','u_panelCount','u_panelCenter','u_panelHalf','u_panelRadius']) {
      loc[n] = gl.getUniformLocation(program, n)
    }

    const verts = new Float32Array([-1,-1, 1,-1, -1,1, 1,1])
    const buf = gl.createBuffer()
    gl.bindBuffer(gl.ARRAY_BUFFER, buf)
    gl.bufferData(gl.ARRAY_BUFFER, verts, gl.STATIC_DRAW)
    const pLoc = gl.getAttribLocation(program, 'a_position')
    gl.enableVertexAttribArray(pLoc)
    gl.vertexAttribPointer(pLoc, 2, gl.FLOAT, false, 8, 0)

    sharpTex = makeTex()
    blurTex = makeTex()
    upload(sharpTex, white())
    upload(blurTex, white())

    try {
      // blur 0..1 → 模糊半径 0..24px（原图尺度）
      const { image, src, aspect } = await buildBlurTexture(o.backgroundUrl, (o.blur ?? 0.16) * 24)
      if (disposed) return
      imageAspect = aspect
      // 玻璃外：清晰原图；玻璃内：预模糊图
      upload(sharpTex, src)
      upload(blurTex, image)
    } catch (e) {
      console.warn(String(e))
    }

    loop()
  })

  onBeforeUnmount(() => {
    disposed = true
    cancelAnimationFrame(raf)
    if (gl) {
      if (sharpTex) gl.deleteTexture(sharpTex)
      if (blurTex) gl.deleteTexture(blurTex)
      if (program) gl.deleteProgram(program)
      gl.getExtension('WEBGL_lose_context')?.loseContext()
    }
    gl = null; program = null; sharpTex = null; blurTex = null
  })
}
