/** 多面板版：一个全屏 canvas 画 N 块圆角玻璃。磨砂来自预模糊纹理，逐帧零开销。 */
// UV 由 gl_FragCoord 计算，避开全屏四边形对角线上的 varying 插值接缝
export const VERTEX_SHADER = `
  attribute vec2 a_position;
  void main() {
    gl_Position = vec4(a_position, 0.0, 1.0);
  }
`

export const MAX_PANELS = 8

export function createFragmentShader(hasDerivatives: boolean): string {
  return `#ifdef GL_OES_standard_derivatives
    #extension GL_OES_standard_derivatives : enable
    #endif
    precision highp float;

    uniform vec2 u_resolution;
    uniform sampler2D u_texture;
    uniform sampler2D u_blurTex;
    uniform vec3 u_tint;
    uniform float u_saturation;
    uniform float u_distortion;
    uniform float u_imageAspect;
    uniform float u_canvasAspect;
    uniform float u_glassMode;
    uniform float u_shadowIntensity;
    uniform vec2 u_shadowOffset;
    uniform float u_shadowBlur;
    uniform float u_chromaticAberration;
    uniform float u_heightRef;
    uniform float u_frost;

    uniform float u_panelCount;
    uniform vec2 u_panelCenter[${MAX_PANELS}];
    uniform vec2 u_panelHalf[${MAX_PANELS}];
    uniform float u_panelRadius[${MAX_PANELS}];

    // 零向量归一化会产生 NaN，进而在后续 min/compare 里扩散成可见伪影
    vec2 safeNormalize(vec2 v) {
      float len = length(v);
      return len > 1e-6 ? v / len : vec2(0.0);
    }

    float sdRoundedRect(vec2 pos, vec2 halfSize, float r) {
      vec2 q = abs(pos) - halfSize + r;
      return min(max(q.x, q.y), 0.0) + length(max(q, 0.0)) - r;
    }

    float combinedSDF(vec2 pos) {
      float d = 1e9;
      for (int i = 0; i < ${MAX_PANELS}; i++) {
        if (float(i) < u_panelCount) {
          d = min(d, sdRoundedRect(pos - u_panelCenter[i], u_panelHalf[i], u_panelRadius[i]));
        }
      }
      return d;
    }

    vec2 getCoverUV(vec2 uv, float imageAspect, float canvasAspect) {
      vec2 coverUV = uv;
      if (imageAspect > canvasAspect) {
        float scale = canvasAspect / imageAspect;
        coverUV.x = (uv.x - 0.5) * scale + 0.5;
      } else {
        float scale = imageAspect / canvasAspect;
        coverUV.y = (uv.y - 0.5) * scale + 0.5;
      }
      return coverUV;
    }

    vec3 saturate(vec3 color, float factor) {
      float gray = dot(color, vec3(0.299, 0.587, 0.114));
      return mix(vec3(gray), color, factor);
    }

    vec2 computeRefractOffset(float sdf, vec2 fragCoord) {
      if (sdf < 0.1) return vec2(0.0);
      ${
        hasDerivatives
          ? `
      vec2 grad = safeNormalize(vec2(dFdx(sdf), dFdy(sdf)));
      `
          : `
      float eps = 2.0;
      float s1 = combinedSDF(fragCoord + vec2(eps, 0.0));
      float s2 = combinedSDF(fragCoord - vec2(eps, 0.0));
      float s3 = combinedSDF(fragCoord + vec2(0.0, eps));
      float s4 = combinedSDF(fragCoord - vec2(0.0, eps));
      vec2 grad = safeNormalize(vec2(s1 - s2, s3 - s4));
      `
      }
      // 越靠近边缘弯折越强，内部保持平直
      float offsetAmount = pow(abs(sdf), 12.0) * -0.05 * u_distortion;
      return grad * offsetAmount;
    }

    float highlight(float sdf, vec2 fragCoord) {
      if (sdf < 0.1) return 0.0;
      ${
        hasDerivatives
          ? `
      vec2 grad = safeNormalize(vec2(dFdx(sdf), dFdy(sdf)));
      `
          : `
      float eps = 2.0;
      float s1 = combinedSDF(fragCoord + vec2(eps, 0.0));
      float s2 = combinedSDF(fragCoord - vec2(eps, 0.0));
      float s3 = combinedSDF(fragCoord + vec2(0.0, eps));
      float s4 = combinedSDF(fragCoord - vec2(0.0, eps));
      vec2 grad = safeNormalize(vec2(s1 - s2, s3 - s4));
      `
      }
      return 1.0 - clamp(pow(1.0 - abs(dot(grad, vec2(-0.707, 0.707))), 0.5), 0.0, 1.0);
    }

    void main() {
      // gl_FragCoord 原点在左下；转成左上为原点的 UV，与 CSS/DOM 坐标一致
      vec2 fragCoord = gl_FragCoord.xy;
      vec2 v_texCoord = vec2(fragCoord.x / u_resolution.x, 1.0 - fragCoord.y / u_resolution.y);
      float sdf = combinedSDF(fragCoord);

      float normalizedInside = (sdf / u_heightRef) + 1.0;
      float edgeBlendFactor = pow(normalizedInside, 12.0);

      vec2 coverUV = getCoverUV(v_texCoord, u_imageAspect, u_canvasAspect);
      vec3 baseTex = texture2D(u_texture, coverUV).rgb;

      // 解析式软投影，只落在玻璃外侧
      float shadowSdf = combinedSDF(fragCoord - u_shadowOffset);
      float shadowMask = (1.0 - smoothstep(0.0, u_shadowBlur, shadowSdf)) * u_shadowIntensity;
      float outside = smoothstep(-1.0, 3.0, sdf);
      vec3 shadowedBackground = baseTex * (1.0 - shadowMask * 0.5 * outside);

      // 内部：采样预模糊纹理，无逐帧模糊开销、无鬼影
      vec2 glassUV = v_texCoord + computeRefractOffset(normalizedInside, fragCoord);
      vec3 frosted = texture2D(u_blurTex, getCoverUV(glassUV, u_imageAspect, u_canvasAspect)).rgb;

      if (u_chromaticAberration > 0.0) {
        vec2 dir = safeNormalize(coverUV - vec2(0.5));
        float k = u_chromaticAberration * 0.003;
        float rr = texture2D(u_blurTex, getCoverUV(glassUV + dir * k, u_imageAspect, u_canvasAspect)).r;
        float bb = texture2D(u_blurTex, getCoverUV(glassUV - dir * k, u_imageAspect, u_canvasAspect)).b;
        frosted = vec3(rr, frosted.g, bb);
      }

      frosted = saturate(frosted, u_saturation);
      frosted *= u_tint;

      // 乳白层：保证面板上的文字可读
      vec3 milk = mix(vec3(0.98, 0.99, 1.0), vec3(0.84, 0.92, 1.0), 0.4);
      frosted = mix(frosted, milk, u_frost);

      if (u_glassMode > 0.5) {
        frosted *= 0.72;
        frosted += mix(0.0, 0.4, clamp(highlight(normalizedInside, fragCoord) * pow(edgeBlendFactor, 3.0), 0.0, 1.0));
      } else {
        frosted += mix(0.0, 0.30, clamp(highlight(normalizedInside, fragCoord) * pow(edgeBlendFactor, 5.0), 0.0, 1.0));
      }

      // 边缘高光细线
      frosted += vec3(smoothstep(2.0, 0.0, abs(sdf)) * 0.35);

      // fwidth 做 1px 抗锯齿，避免硬边
      float aa = fwidth(sdf) + 1e-5;
      float boxMask = 1.0 - smoothstep(-aa, aa, sdf);
      gl_FragColor = vec4(mix(shadowedBackground, frosted, vec3(boxMask)), 1.0);
    }
  `
}
