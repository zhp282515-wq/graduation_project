/**
 * GLSL sources for the liquid glass effect.
 *
 * The fragment shader is a 1:1 port of the original React implementation —
 * it is framework agnostic and lives here so it can be reused (or tested)
 * without touching any component.
 */

export const VERTEX_SHADER = `
  attribute vec2 a_position;
  attribute vec2 a_texCoord;
  varying vec2 v_texCoord;

  void main() {
    gl_Position = vec4(a_position, 0.0, 1.0);
    v_texCoord = a_texCoord;
  }
`

const BODY = (hasDerivatives: boolean) => `
    precision mediump float;

    uniform float u_time;
    uniform vec2 u_resolution;
    uniform vec2 u_mouse;
    uniform sampler2D u_texture;
    uniform float u_width;
    uniform float u_height;
    uniform vec3 u_tint;
    uniform float u_saturation;
    uniform float u_distortion;
    uniform float u_blur;
    uniform float u_imageAspect;
    uniform float u_canvasAspect;
    uniform float u_glassMode;
    uniform float u_shadowIntensity;
    uniform vec2 u_shadowOffset;
    uniform float u_shadowBlur;
    uniform float u_cornerRadius;
    uniform float u_chromaticAberration;
    uniform float u_shape;
    uniform float u_donutThickness;
    uniform float u_starPoints;
    uniform float u_starInnerRadius;

    varying vec2 v_texCoord;

    #define PI 3.141592653589793

    vec2 getCoverUV(vec2 uv, float imageAspect, float canvasAspect) {
      vec2 coverUV = uv;

      if (imageAspect > canvasAspect) {
        // Image is wider than canvas - fit height, crop width
        float scale = canvasAspect / imageAspect;
        coverUV.x = (uv.x - 0.5) * scale + 0.5;
      } else {
        // Image is taller than canvas - fit width, crop height
        float scale = imageAspect / canvasAspect;
        coverUV.y = (uv.y - 0.5) * scale + 0.5;
      }

      return coverUV;
    }

    // Shape SDF functions
    float sdRoundedRect(vec2 pos, vec2 halfSize, vec4 cornerRadius) {
      cornerRadius.xy = (pos.x > 0.0) ? cornerRadius.xy : cornerRadius.zw;
      cornerRadius.x = (pos.y > 0.0) ? cornerRadius.x : cornerRadius.y;

      vec2 q = abs(pos) - halfSize + cornerRadius.x;
      return min(max(q.x, q.y), 0.0) + length(max(q, 0.0)) - cornerRadius.x;
    }

    float sdCircle(vec2 pos, float radius) {
      return length(pos) - radius;
    }

    // Star SDF with inner radius control
    float sdStar(vec2 pos, float outerRadius, float innerRadius, int points) {
      float angle = atan(pos.y, pos.x);
      float radius = length(pos);

      // Segment angle
      float segmentAngle = 2.0 * PI / float(points);

      // Find which segment we're in
      float segment = floor(angle / segmentAngle + 0.5);
      float segmentStart = segment * segmentAngle;

      // Local angle within segment
      float localAngle = angle - segmentStart;

      // Distance to star edge
      float halfSegment = segmentAngle * 0.5;

      // Interpolate between inner and outer radius based on angle
      float t = abs(localAngle) / halfSegment;
      float targetRadius = mix(outerRadius, innerRadius, t);

      return radius - targetRadius;
    }

    float sdHexagon(vec2 pos, float size) {
      const vec3 k = vec3(-0.866025404, 0.5, 0.577350269);
      pos = abs(pos);
      pos -= 2.0 * min(dot(k.xy, pos), 0.0) * k.xy;
      pos -= vec2(clamp(pos.x, -k.z * size, k.z * size), size);
      return length(pos) * sign(pos.y);
    }

    float sdDonut(vec2 pos, float outerRadius, float thickness) {
      float innerRadius = outerRadius * (1.0 - thickness);
      float d = length(pos);
      return max(d - outerRadius, innerRadius - d);
    }

    float getShapeSDF(vec2 pos) {
      if (u_shape < 0.5) {
        // Rectangle
        return sdRoundedRect(pos, vec2(u_width, u_height), vec4(u_cornerRadius));
      } else if (u_shape < 1.5) {
        // Circle
        float radius = min(u_width, u_height);
        return sdCircle(pos, radius);
      } else if (u_shape < 2.5) {
        // Star
        float outerRadius = min(u_width, u_height) * 0.8;
        float innerRadius = outerRadius * u_starInnerRadius;
        return sdStar(pos, outerRadius, innerRadius, int(u_starPoints));
      } else if (u_shape < 3.5) {
        // Hexagon
        float size = min(u_width, u_height) * 0.8;
        return sdHexagon(pos, size);
      } else {
        // Donut
        float radius = min(u_width, u_height) * 0.8;
        return sdDonut(pos, radius, u_donutThickness);
      }
    }

    float boxSDF(vec2 uv) {
      return getShapeSDF(uv);
    }

    float shadowSDF(vec2 uv) {
      vec2 shadowPos = uv - u_shadowOffset;
      return getShapeSDF(shadowPos);
    }

    vec2 randomVec2(vec2 co) {
      return fract(sin(vec2(
        dot(co, vec2(127.1, 311.7)),
        dot(co, vec2(269.5, 183.3))
      )) * 43758.5453);
    }

    vec3 sampleWithNoise(vec2 uv, float timeOffset, float mipLevel) {
      vec2 coverUV = getCoverUV(uv, u_imageAspect, u_canvasAspect);
      vec2 offset = randomVec2(coverUV + vec2(u_time + timeOffset)) / u_resolution.x;
      return texture2D(u_texture, coverUV + offset * pow(2.0, mipLevel) * 0.01).rgb;
    }

    vec3 sampleWithChromaticAberration(vec2 uv, float timeOffset, float mipLevel, float aberrationStrength) {
      if (aberrationStrength <= 0.0) {
        return sampleWithNoise(uv, timeOffset, mipLevel);
      }

      vec2 coverUV = getCoverUV(uv, u_imageAspect, u_canvasAspect);
      vec2 center = vec2(0.5);
      vec2 direction = normalize(coverUV - center);
      float distance = length(coverUV - center);

      // Calculate chromatic aberration offsets based on distance from center
      float aberrationOffset = aberrationStrength * distance * 0.01;

      vec2 offset = randomVec2(coverUV + vec2(u_time + timeOffset)) / u_resolution.x;
      vec2 noiseOffset = offset * pow(2.0, mipLevel) * 0.01;

      // Sample each channel with different offsets
      float r = texture2D(u_texture, coverUV + direction * aberrationOffset * 1.2 + noiseOffset).r;
      float g = texture2D(u_texture, coverUV + noiseOffset).g;
      float b = texture2D(u_texture, coverUV - direction * aberrationOffset * 0.8 + noiseOffset).b;

      return vec3(r, g, b);
    }

    vec3 getBlurredColor(vec2 uv, float mipLevel) {
      return (
        sampleWithChromaticAberration(uv, 0.0, mipLevel, u_chromaticAberration) +
        sampleWithChromaticAberration(uv, 0.25, mipLevel, u_chromaticAberration) +
        sampleWithChromaticAberration(uv, 0.5, mipLevel, u_chromaticAberration) +
        sampleWithChromaticAberration(uv, 0.75, mipLevel, u_chromaticAberration) +
        sampleWithChromaticAberration(uv, 1.0, mipLevel, u_chromaticAberration) +
        sampleWithChromaticAberration(uv, 1.25, mipLevel, u_chromaticAberration) +
        sampleWithChromaticAberration(uv, 1.5, mipLevel, u_chromaticAberration) +
        sampleWithChromaticAberration(uv, 1.75, mipLevel, u_chromaticAberration) +
        sampleWithChromaticAberration(uv, 2.0, mipLevel, u_chromaticAberration)
      ) * 0.11111;
    }

    vec3 saturate(vec3 color, float factor) {
      float gray = dot(color, vec3(0.299, 0.587, 0.114));
      return mix(vec3(gray), color, factor);
    }

    vec2 computeRefractOffset(float sdf, vec2 fragCoord) {
      if (sdf < 0.1) {
        return vec2(0.0);
      }

      ${
        hasDerivatives
          ? `
      #ifdef GL_OES_standard_derivatives
      vec2 grad = normalize(vec2(dFdx(sdf), dFdy(sdf)));
      #else
      vec2 grad = normalize(vec2(0.1, 0.1));
      #endif
      `
          : `
      // Approximate gradient using manual sampling
      float epsilon = 2.0;
      vec2 h = vec2(epsilon, 0.0);
      vec2 centeredUV1 = (fragCoord + h.xy) - u_mouse;
      vec2 centeredUV2 = (fragCoord - h.xy) - u_mouse;
      vec2 centeredUV3 = (fragCoord + h.yx) - u_mouse;
      vec2 centeredUV4 = (fragCoord - h.yx) - u_mouse;

      float sdf1 = boxSDF(centeredUV1);
      float sdf2 = boxSDF(centeredUV2);
      float sdf3 = boxSDF(centeredUV3);
      float sdf4 = boxSDF(centeredUV4);

      vec2 grad = normalize(vec2(sdf1 - sdf2, sdf3 - sdf4));
      `
      }

      float offsetAmount = pow(abs(sdf), 12.0) * -0.05 * u_distortion;
      return grad * offsetAmount;
    }

    float highlight(float sdf, vec2 fragCoord) {
      if (sdf < 0.1) {
        return 0.0;
      }

      ${
        hasDerivatives
          ? `
      #ifdef GL_OES_standard_derivatives
      vec2 grad = normalize(vec2(dFdx(sdf), dFdy(sdf)));
      #else
      vec2 grad = normalize(vec2(0.1, 0.1));
      #endif
      `
          : `
      // Approximate gradient using manual sampling
      float epsilon = 2.0;
      vec2 h = vec2(epsilon, 0.0);
      vec2 centeredUV1 = (fragCoord + h.xy) - u_mouse;
      vec2 centeredUV2 = (fragCoord - h.xy) - u_mouse;
      vec2 centeredUV3 = (fragCoord + h.yx) - u_mouse;
      vec2 centeredUV4 = (fragCoord - h.yx) - u_mouse;

      float sdf1 = boxSDF(centeredUV1);
      float sdf2 = boxSDF(centeredUV2);
      float sdf3 = boxSDF(centeredUV3);
      float sdf4 = boxSDF(centeredUV4);

      vec2 grad = normalize(vec2(sdf1 - sdf2, sdf3 - sdf4));
      `
      }

      return 1.0 - clamp(pow(1.0 - abs(dot(grad, vec2(-0.707, 0.707))), 0.5), 0.0, 1.0);
    }

    float gaussianBlur(vec2 uv, float blurSize) {
      float total = 0.0;
      float totalWeight = 0.0;
      float radius = min(blurSize, 15.0); // Clamp to max radius of 15

      // Use constant loop bounds and conditional execution
      for (int x = -15; x <= 15; x++) {
        for (int y = -15; y <= 15; y++) {
          // Only process if within the desired radius
          if (float(x) >= -radius && float(x) <= radius &&
              float(y) >= -radius && float(y) <= radius) {

            vec2 offset = vec2(float(x), float(y)) / u_resolution;
            vec2 samplePos = (uv * u_resolution + vec2(float(x), float(y))) - u_mouse;
            float weight = exp(-(float(x*x + y*y)) / (2.0 * radius * radius));
            float shadowValue = 1.0 - clamp(shadowSDF(samplePos), 0.0, 1.0);

            total += weight * shadowValue;
            totalWeight += weight;
          }
        }
      }

      return totalWeight > 0.0 ? total / totalWeight : 0.0;
    }

    void main() {
      vec2 fragCoord = v_texCoord * u_resolution;
      vec2 centeredUV = fragCoord - u_mouse;
      float sdf = boxSDF(centeredUV);

      float normalizedInside = (sdf / u_height) + 1.0;
      float edgeBlendFactor = pow(normalizedInside, 12.0);

      vec2 coverUV = getCoverUV(v_texCoord, u_imageAspect, u_canvasAspect);
      vec3 baseTex = texture2D(u_texture, coverUV).rgb;

      // Shadow rendering
      float shadowMask = 0.0;
      if (u_shadowIntensity > 0.0) {
        shadowMask = gaussianBlur(v_texCoord, u_shadowBlur);
        shadowMask *= u_shadowIntensity;
      }

      vec2 sampleUV = v_texCoord + computeRefractOffset(normalizedInside, fragCoord);
      float mipLevel = mix(3.5 * u_blur, 1.5, edgeBlendFactor);

      // Get blurred color with chromatic aberration
      vec3 blurredTex = getBlurredColor(sampleUV, mipLevel);

      // Apply saturation and edge blending
      blurredTex = mix(blurredTex, pow(saturate(blurredTex, u_saturation), vec3(0.5)), edgeBlendFactor);

      // Apply tint
      blurredTex *= u_tint;

      // Glass mode adjustments
      if (u_glassMode > 0.5) {
        // Dark glass mode
        blurredTex = mix(blurredTex, blurredTex * 0.7, 0.3);
        blurredTex += mix(0.0, 0.4, clamp(highlight(normalizedInside, fragCoord) * pow(edgeBlendFactor, 3.0), 0.0, 1.0));

        // Enhanced rim lighting for dark glass
        float rimLight = smoothstep(0.0, 0.2, sdf) * smoothstep(1.5, 0.3, sdf) * 0.15;
        blurredTex += vec3(rimLight);
      } else {
        // Light glass mode
        blurredTex += mix(0.0, 0.3, clamp(highlight(normalizedInside, fragCoord) * pow(edgeBlendFactor, 5.0), 0.0, 1.0));

        // Subtle brightness boost for light glass
        blurredTex = mix(blurredTex, blurredTex * 1.1, 0.2);
      }

      float boxMask = 1.0 - clamp(sdf, 0.0, 1.0);

      // Apply shadow to background
      vec3 shadowedBackground = mix(baseTex, baseTex * (1.0 - shadowMask), step(0.01, shadowMask));

      gl_FragColor = vec4(mix(shadowedBackground, blurredTex, vec3(boxMask)), 1.0);
    }
`

export function createFragmentShader(hasDerivatives: boolean): string {
  return `#ifdef GL_OES_standard_derivatives
    #extension GL_OES_standard_derivatives : enable
    #endif
    ${BODY(hasDerivatives)}`
}
