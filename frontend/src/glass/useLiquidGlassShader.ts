import { onBeforeUnmount, onMounted, watch, type Ref } from 'vue'
import { createFragmentShader, VERTEX_SHADER } from './glass'

export type GlassShape = 'rectangle' | 'circle' | 'star' | 'hexagon' | 'donut'

export interface ShaderUniforms {
  width: number
  height: number
  mouseX: number
  mouseY: number
  tintR: number
  tintG: number
  tintB: number
  saturation: number
  distortion: number
  blur: number
  text: string
  iconSize: number
  iconColorR: number
  iconColorG: number
  iconColorB: number
  glassMode: 'light' | 'dark'
  shadowIntensity: number
  shadowOffsetX: number
  shadowOffsetY: number
  shadowBlur: number
  cornerRadius: number
  chromaticAberration: number
  shape: GlassShape
  donutThickness: number
  starPoints: number
  starInnerRadius: number
}

export interface BackgroundMedia {
  url: string
  type: 'image' | 'video'
  blurhash?: string
}

interface Options {
  canvas: Ref<HTMLCanvasElement | null>
  uniforms: ShaderUniforms
  background: Ref<BackgroundMedia>
  onReady?: () => void
}

const SHAPE_INDEX: Record<GlassShape, number> = {
  rectangle: 0,
  circle: 1,
  star: 2,
  hexagon: 3,
  donut: 4,
}

const UNIFORM_NAMES = [
  'u_time',
  'u_resolution',
  'u_mouse',
  'u_texture',
  'u_width',
  'u_height',
  'u_tint',
  'u_saturation',
  'u_distortion',
  'u_blur',
  'u_imageAspect',
  'u_canvasAspect',
  'u_glassMode',
  'u_shadowIntensity',
  'u_shadowOffset',
  'u_shadowBlur',
  'u_cornerRadius',
  'u_chromaticAberration',
  'u_shape',
  'u_donutThickness',
  'u_starPoints',
  'u_starInnerRadius',
]

/**
 * Owns the whole WebGL lifecycle for the glass canvas: shader compilation,
 * texture uploads (image / video), the animation loop and cleanup.
 *
 * Nothing here is Vue-specific beyond `onMounted` / `onBeforeUnmount` — the
 * uniforms are read from a plain reactive object on every frame.
 */
export function useLiquidGlassShader({ canvas, uniforms, background, onReady }: Options) {
  let gl: WebGLRenderingContext | null = null
  let program: WebGLProgram | null = null
  let texture: WebGLTexture | null = null
  let video: HTMLVideoElement | null = null
  let rafId = 0
  let startTime = Date.now()
  let imageAspect = 1
  let lastSize = ''
  let mediaVersion = 0
  let readyTimer: ReturnType<typeof setTimeout> | undefined
  let disposed = false
  let locations: Record<string, WebGLUniformLocation | null> = {}

  const compileShader = (type: number, source: string): WebGLShader | null => {
    if (!gl) return null
    const shader = gl.createShader(type)
    if (!shader) return null

    gl.shaderSource(shader, source)
    gl.compileShader(shader)

    if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
      console.error('Shader compilation error:', gl.getShaderInfoLog(shader))
      gl.deleteShader(shader)
      return null
    }

    return shader
  }

  const createWhiteCanvas = (): HTMLCanvasElement => {
    const canvas2d = document.createElement('canvas')
    canvas2d.width = canvas2d.height = 512
    const ctx = canvas2d.getContext('2d')!
    ctx.fillStyle = '#ffffff'
    ctx.fillRect(0, 0, 512, 512)
    return canvas2d
  }

  const applyTextureParams = () => {
    if (!gl) return
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE)
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE)
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR)
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR)
  }

  const uploadTexture = (source: TexImageSource) => {
    if (!gl || !texture) return
    gl.bindTexture(gl.TEXTURE_2D, texture)
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, source)
    applyTextureParams()
  }

  const stopVideo = () => {
    if (!video) return
    video.pause()
    video.removeAttribute('src')
    video.load()
    video = null
  }

  const loadMedia = (media: BackgroundMedia) => {
    if (!gl || !texture || disposed) return

    const version = ++mediaVersion

    // Always start from a neutral white so switching never flashes the old image.
    uploadTexture(createWhiteCanvas())

    if (media.type === 'video') {
      stopVideo()

      const el = document.createElement('video')
      el.crossOrigin = 'anonymous'
      el.muted = true
      el.loop = true
      el.playsInline = true
      el.autoplay = true

      el.addEventListener('loadedmetadata', () => {
        if (el.videoWidth && el.videoHeight) {
          imageAspect = el.videoWidth / el.videoHeight
        }
      })

      el.addEventListener('canplaythrough', () => {
        el.play().catch((error) => console.warn('Video autoplay failed:', error))
      })

      el.src = media.url
      video = el
      return
    }

    stopVideo()

    if (!media.url) return

    const image = new Image()
    image.crossOrigin = 'anonymous'
    image.onload = () => {
      if (disposed || version !== mediaVersion) return
      imageAspect = image.width / image.height
      uploadTexture(image)
    }
    image.onerror = () => console.warn('Failed to load image:', media.url)
    image.src = media.url
  }

  const updateVideoTexture = () => {
    if (!gl || !texture || !video) return
    if (video.readyState >= video.HAVE_CURRENT_DATA) {
      uploadTexture(video)
    }
  }

  const setupQuad = () => {
    if (!gl || !program) return

    // Full screen quad, texture coordinates flipped on Y.
    const vertices = new Float32Array([
      -1, -1, 0, 1,
      1, -1, 1, 1,
      -1, 1, 0, 0,
      1, 1, 1, 0,
    ])

    const buffer = gl.createBuffer()
    gl.bindBuffer(gl.ARRAY_BUFFER, buffer)
    gl.bufferData(gl.ARRAY_BUFFER, vertices, gl.STATIC_DRAW)

    const positionLocation = gl.getAttribLocation(program, 'a_position')
    const texCoordLocation = gl.getAttribLocation(program, 'a_texCoord')

    gl.enableVertexAttribArray(positionLocation)
    gl.enableVertexAttribArray(texCoordLocation)
    gl.vertexAttribPointer(positionLocation, 2, gl.FLOAT, false, 16, 0)
    gl.vertexAttribPointer(texCoordLocation, 2, gl.FLOAT, false, 16, 8)
  }

  const draw = () => {
    const el = canvas.value
    if (!el || !gl || !program || !texture) return

    const size = `${el.offsetWidth}x${el.offsetHeight}`
    if (lastSize !== size) {
      el.width = el.offsetWidth * devicePixelRatio
      el.height = el.offsetHeight * devicePixelRatio
      gl.viewport(0, 0, el.width, el.height)
      lastSize = size
    }

    if (video && background.value.type === 'video') {
      updateVideoTexture()
    }

    gl.useProgram(program)

    gl.uniform1f(locations.u_time, (Date.now() - startTime) / 1000)
    gl.uniform2f(locations.u_resolution, el.width, el.height)
    gl.uniform2f(locations.u_mouse, uniforms.mouseX * devicePixelRatio, uniforms.mouseY * devicePixelRatio)
    gl.uniform1i(locations.u_texture, 0)
    gl.uniform1f(locations.u_width, uniforms.width)
    gl.uniform1f(locations.u_height, uniforms.height)
    gl.uniform3f(locations.u_tint, uniforms.tintR, uniforms.tintG, uniforms.tintB)
    gl.uniform1f(locations.u_saturation, uniforms.saturation)
    gl.uniform1f(locations.u_distortion, uniforms.distortion)
    gl.uniform1f(locations.u_blur, uniforms.blur)
    gl.uniform1f(locations.u_imageAspect, imageAspect)
    gl.uniform1f(locations.u_canvasAspect, el.width / el.height)
    gl.uniform1f(locations.u_glassMode, uniforms.glassMode === 'dark' ? 1 : 0)
    gl.uniform1f(locations.u_shadowIntensity, uniforms.shadowIntensity)
    gl.uniform2f(locations.u_shadowOffset, uniforms.shadowOffsetX, uniforms.shadowOffsetY)
    gl.uniform1f(locations.u_shadowBlur, uniforms.shadowBlur)
    gl.uniform1f(locations.u_cornerRadius, uniforms.cornerRadius)
    gl.uniform1f(locations.u_chromaticAberration, uniforms.chromaticAberration)
    gl.uniform1f(locations.u_shape, SHAPE_INDEX[uniforms.shape] ?? 0)
    gl.uniform1f(locations.u_donutThickness, uniforms.donutThickness)
    gl.uniform1f(locations.u_starPoints, uniforms.starPoints)
    gl.uniform1f(locations.u_starInnerRadius, uniforms.starInnerRadius)

    gl.activeTexture(gl.TEXTURE0)
    gl.bindTexture(gl.TEXTURE_2D, texture)

    gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4)
  }

  const loop = () => {
    if (disposed) return
    draw()
    rafId = requestAnimationFrame(loop)
  }

  onMounted(() => {
    const el = canvas.value
    if (!el) return

    gl = el.getContext('webgl')
    if (!gl) {
      console.error('WebGL not supported')
      return
    }

    const hasDerivatives = !!gl.getExtension('OES_standard_derivatives')

    const vertexShader = compileShader(gl.VERTEX_SHADER, VERTEX_SHADER)
    const fragmentShader = compileShader(gl.FRAGMENT_SHADER, createFragmentShader(hasDerivatives))
    if (!vertexShader || !fragmentShader) return

    const linked = gl.createProgram()
    if (!linked) return
    gl.attachShader(linked, vertexShader)
    gl.attachShader(linked, fragmentShader)
    gl.linkProgram(linked)
    if (!gl.getProgramParameter(linked, gl.LINK_STATUS)) {
      console.error('Program linking error:', gl.getProgramInfoLog(linked))
      return
    }

    program = linked
    locations = {}
    for (const name of UNIFORM_NAMES) {
      locations[name] = gl.getUniformLocation(program, name)
    }

    setupQuad()

    texture = gl.createTexture()
    uploadTexture(createWhiteCanvas())
    loadMedia(background.value)

    startTime = Date.now()
    loop()

    readyTimer = setTimeout(() => onReady?.(), 200)
  })

  watch(background, (media) => {
    loadMedia(media)
  })

  onBeforeUnmount(() => {
    disposed = true
    cancelAnimationFrame(rafId)
    if (readyTimer) clearTimeout(readyTimer)
    stopVideo()
    if (gl) {
      if (texture) gl.deleteTexture(texture)
      if (program) gl.deleteProgram(program)
      gl.getExtension('WEBGL_lose_context')?.loseContext()
    }
    gl = null
    program = null
    texture = null
  })
}
