/**
 * 液态玻璃面板层 —— liquid-glass-js `container.js` 的 WebGL 着色器移植
 * ===========================================================================
 * 原库每个玻璃元素各自建一个 canvas + WebGL 上下文，用 html2canvas 把整页截一张图
 * 当纹理，然后对着色器做边缘/轮廓折射 + 高斯模糊 + 白灰渐变染色。
 *
 * 本项目里背景是 ParticleDrift 的实时粒子（WebGL canvas，透明底 + 预乘 alpha），
 * 截静态快照会立刻和动画脱节，所以这里做四处方差、全部可视等价：
 *
 *  1. 纹理来源：不截页面，直接把粒子 canvas 每帧上传成纹理（preserveDrawingBuffer）。
 *  2. 面板背后那一片背景的 UV，按面板在屏幕上的位置换算：
 *       pixel = u_origin + coord * u_size      （原版的 pagePixel = containerCenter + offset）
 *  3. 原版每像素重算的「顶部/中部/底部三带采样」（20×11×3 ≈ 660 次采样）其实
 *     与 coord 无关、整块玻璃是同一个常量。这里省掉——它对最终颜色的权重是
 *     tintOpacity * 0.3 = 3%，与本项目接近纯黑的背景做混合等于没变化。
 *  4. 高斯的 169 个 tap 里，权重 < 1e-4 的（blurRadius=1 时 |d| > 2）直接跳过，
 *     归一化仍按实际求和，结果与全量循环逐位一致。
 * 另外补了一处：粒子 canvas 是预乘 alpha，页面底色由 u_backdrop 在着色器里合成。
 *
 * 折射、波纹、四角增益、遮罩的数学与原版逐行一致，参数默认取 myconfig 预设。
 */

import { LIQUID_GLASS_PRESET } from './preset'

const VERT_SOURCE = `
attribute vec2 a_position;
attribute vec2 a_texcoord;
varying vec2 v_texcoord;

void main() {
  gl_Position = vec4(a_position, 0, 1);
  v_texcoord = a_texcoord;
}
`

const FRAG_SOURCE = `
#ifdef GL_FRAGMENT_PRECISION_HIGH
precision highp float;
#else
precision mediump float;
#endif

uniform sampler2D u_image;
uniform vec2  u_resolution;     // 面板尺寸（canvas 像素）
uniform vec2  u_textureSize;    // 背景纹理尺寸
uniform vec2  u_origin;         // 面板左上角在纹理里的位置（纹理像素）
uniform vec2  u_size;           // 面板尺寸（纹理像素）
uniform float u_borderRadius;
uniform float u_blurRadius;
uniform float u_tapLimit;       // 高斯核的截断半径
uniform float u_warp;
uniform float u_edgeIntensity;
uniform float u_rimIntensity;
uniform float u_baseIntensity;
uniform float u_edgeDistance;
uniform float u_rimDistance;
uniform float u_baseDistance;
uniform float u_cornerBoost;
uniform float u_rippleEffect;
uniform float u_tintOpacity;
uniform vec3  u_tintColor;      // 染色目标色（原库是白→灰，深色界面改成页面底色）
uniform float u_alpha;          // 面板自身透明度（左右栏收起时跟着淡出）
uniform vec3  u_backdrop;       // 页面底色（粒子层是透明底，要自己合成）

varying vec2 v_texcoord;

// 到圆角矩形边缘的距离（内部为负）
float roundedRectDistance(vec2 coord, vec2 size, float radius) {
  vec2 center = size * 0.5;
  vec2 pixelCoord = coord * size;
  vec2 toCorner = abs(pixelCoord - center) - (center - radius);
  float outsideCorner = length(max(toCorner, 0.0));
  float insideCorner = min(max(toCorner.x, toCorner.y), 0.0);
  return (outsideCorner + insideCorner - radius);
}

// 到圆形边缘的距离
float circleDistance(vec2 coord, vec2 size, float radius) {
  vec2 center = vec2(0.5, 0.5);
  vec2 pixelCoord = coord * size;
  vec2 centerPixel = center * size;
  float distFromCenter = length(pixelCoord - centerPixel);
  return distFromCenter - radius;
}

bool isPill(vec2 size, float radius) {
  float heightRatioDiff = abs(radius - size.y * 0.5);
  bool radiusMatchesHeight = heightRatioDiff < 2.0;
  bool isWiderThanTall = size.x > size.y + 4.0;
  return radiusMatchesHeight && isWiderThanTall;
}

bool isCircle(vec2 size, float radius) {
  float minDim = min(size.x, size.y);
  bool radiusMatchesMinDim = abs(radius - minDim * 0.5) < 1.0;
  bool isRoughlySquare = abs(size.x - size.y) < 4.0;
  return radiusMatchesMinDim && isRoughlySquare;
}

// 到胶囊（pill）边缘的距离
float pillDistance(vec2 coord, vec2 size, float radius) {
  vec2 center = size * 0.5;
  vec2 pixelCoord = coord * size;

  vec2 capsuleStart = vec2(radius, center.y);
  vec2 capsuleEnd = vec2(size.x - radius, center.y);
  vec2 capsuleAxis = capsuleEnd - capsuleStart;
  float capsuleLength = length(capsuleAxis);

  if (capsuleLength > 0.0) {
    vec2 toPoint = pixelCoord - capsuleStart;
    float t = clamp(dot(toPoint, capsuleAxis) / dot(capsuleAxis, capsuleAxis), 0.0, 1.0);
    vec2 closestPointOnAxis = capsuleStart + t * capsuleAxis;
    return length(pixelCoord - closestPointOnAxis) - radius;
  } else {
    return length(pixelCoord - center) - radius;
  }
}

void main() {
  vec2 coord = v_texcoord;

  // 这块玻璃背后那一片背景（原版是整个页面快照，这里是实时粒子层）
  vec2 pixel = u_origin + coord * u_size;
  vec2 textureCoord = pixel / u_textureSize;

  float distFromEdgeShape;
  vec2 shapeNormal; // 指向形状外侧的法线

  if (isPill(u_resolution, u_borderRadius)) {
    distFromEdgeShape = -pillDistance(coord, u_resolution, u_borderRadius);

    vec2 center = vec2(0.5, 0.5);
    vec2 pixelCoord = coord * u_resolution;
    vec2 capsuleStart = vec2(u_borderRadius, center.y * u_resolution.y);
    vec2 capsuleEnd = vec2(u_resolution.x - u_borderRadius, center.y * u_resolution.y);
    vec2 capsuleAxis = capsuleEnd - capsuleStart;
    float capsuleLength = length(capsuleAxis);

    if (capsuleLength > 0.0) {
      vec2 toPoint = pixelCoord - capsuleStart;
      float t = clamp(dot(toPoint, capsuleAxis) / dot(capsuleAxis, capsuleAxis), 0.0, 1.0);
      vec2 closestPointOnAxis = capsuleStart + t * capsuleAxis;
      vec2 normalDir = pixelCoord - closestPointOnAxis;
      shapeNormal = length(normalDir) > 0.0 ? normalize(normalDir) : vec2(0.0, 1.0);
    } else {
      shapeNormal = normalize(coord - center);
    }
  } else if (isCircle(u_resolution, u_borderRadius)) {
    distFromEdgeShape = -circleDistance(coord, u_resolution, u_borderRadius);
    vec2 center = vec2(0.5, 0.5);
    shapeNormal = normalize(coord - center);
  } else {
    distFromEdgeShape = -roundedRectDistance(coord, u_resolution, u_borderRadius);
    vec2 center = vec2(0.5, 0.5);
    shapeNormal = normalize(coord - center);
  }
  distFromEdgeShape = max(distFromEdgeShape, 0.0);

  float distFromLeft = coord.x;
  float distFromRight = 1.0 - coord.x;
  float distFromTop = coord.y;
  float distFromBottom = 1.0 - coord.y;
  float distFromEdge = distFromEdgeShape / min(u_resolution.x, u_resolution.y);

  // 沿法线的折射量：base(仅 warp) + edge + rim，都是指数衰减
  float normalizedDistance = distFromEdge * min(u_resolution.x, u_resolution.y);
  float baseIntensity = 1.0 - exp(-normalizedDistance * u_baseDistance);
  float edgeIntensity = exp(-normalizedDistance * u_edgeDistance);
  float rimIntensity = exp(-normalizedDistance * u_rimDistance);

  float baseComponent = u_warp > 0.5 ? baseIntensity * u_baseIntensity : 0.0;
  float totalIntensity = baseComponent + edgeIntensity * u_edgeIntensity + rimIntensity * u_rimIntensity;

  vec2 baseRefraction = shapeNormal * totalIntensity;

  // 四角额外增益
  float cornerProximityX = min(distFromLeft, distFromRight);
  float cornerProximityY = min(distFromTop, distFromBottom);
  float cornerDistance = max(cornerProximityX, cornerProximityY);
  float cornerNormalized = cornerDistance * min(u_resolution.x, u_resolution.y);

  float cornerBoost = exp(-cornerNormalized * 0.3) * u_cornerBoost;
  vec2 cornerRefraction = shapeNormal * cornerBoost;

  // 沿切向的波纹
  vec2 perpendicular = vec2(-shapeNormal.y, shapeNormal.x);
  float rippleEffect = sin(distFromEdge * 25.0) * u_rippleEffect * rimIntensity;
  vec2 textureRefraction = perpendicular * rippleEffect;

  vec2 totalRefraction = baseRefraction + cornerRefraction + textureRefraction;
  textureCoord += totalRefraction;

  // 高斯模糊（sigma = blurRadius / 2），截断掉权重可忽略的 tap
  vec4 color = vec4(0.0);
  vec2 texelSize = 1.0 / u_textureSize;
  // 下限 1e-3：blurRadius=0 时 sigma=0 会让 exp() 的指数变 NaN，整块玻璃直接不显示
  float sigma = max(u_blurRadius * 0.5, 1e-3);
  vec2 blurStep = texelSize * sigma;

  float totalWeight = 0.0;

  for (float i = -6.0; i <= 6.0; i += 1.0) {
    for (float j = -6.0; j <= 6.0; j += 1.0) {
      float distance = length(vec2(i, j));
      if (distance > 6.0) continue;
      if (distance > u_tapLimit) continue;

      float weight = exp(-(distance * distance) / (2.0 * sigma * sigma));

      vec2 offset = vec2(i, j) * blurStep;
      color += texture2D(u_image, textureCoord + offset) * weight;
      totalWeight += weight;
    }
  }

  color /= totalWeight;

  // 粒子层是透明底的预乘 alpha，先把页面底色合进来
  vec3 base = color.rgb + u_backdrop * (1.0 - color.a);

  // 竖直渐变染色。原库往「白→灰」方向染，是因为它的 demo 页是浅色照片背景；
  // 本项目是深色界面，往白染只会把背后的粒子网洗成灰雾（对比度被压缩到
  // 0.2..1 区间却依然看得见形状），所以染色目标色做成 uniform：
  // 默认往页面底色方向染 ⇒ 面板变成一层压暗的深色玻璃，网线退成底纹，
  // 面板与背景之间出现明确的明度台阶，文字才有安静的落脚点。
  float gradientPosition = coord.y;
  vec3 topTint = u_tintColor * 1.18;
  vec3 bottomTint = u_tintColor * 0.86;
  vec3 gradientTint = mix(topTint, bottomTint, gradientPosition);
  vec3 finalColor = mix(base, gradientTint, u_tintOpacity);

  // 形状遮罩
  float maskDistance;
  if (isPill(u_resolution, u_borderRadius)) {
    maskDistance = pillDistance(coord, u_resolution, u_borderRadius);
  } else if (isCircle(u_resolution, u_borderRadius)) {
    maskDistance = circleDistance(coord, u_resolution, u_borderRadius);
  } else {
    maskDistance = roundedRectDistance(coord, u_resolution, u_borderRadius);
  }
  float mask = 1.0 - smoothstep(-1.0, 1.0, maskDistance);

  // canvas 是 premultiplied alpha，跟着乘 mask 才不会在描边处发亮
  float alpha = mask * u_alpha;
  gl_FragColor = vec4(finalColor * alpha, alpha);
}
`

/**
 * 按钮专用片元着色器 —— 逐行移植自 liquid-glass-js 的 button.js
 * (`setupDynamicNestedShader`)。
 *
 * 与上面容器版的三处真实差别（不是我的发挥，是原库自己就这么写）：
 *   1. 高斯 σ = blurRadius / 3（容器版是 /2），核半径固定 4，9×9 采样；
 *   2. 波纹频率 30（容器版 25）：sin(distFromEdge * 30.0)；
 *   3. 染色是三层：写死的「白→灰」竖直渐变（权重 tintOpacity*0.7）、
 *      再按按钮竖直方向从底下取三条色带插值（权重 tintOpacity*0.4）、
 *      最后乘一个「上 1.08 / 下 0.92」的亮度斜坡。
 *
 * 原库按钮是嵌在容器里的，纹理直接取父容器 canvas；本项目的按钮嵌在
 * CSS 玻璃面板里，纹理是实时粒子层、面板色不在里面，所以：
 *   - 形状函数与容器版同一份（GLSL 没有 include，只能复制）；
 *   - u_backdrop 传的是"面板底色"（见 panelBackdrop()），先合成出按钮背后
 *     那层面板，再往上染；否则按钮会像直接长在黑色页面上。
 *   - u_tintColor 原库写死白色，这里留成 uniform：默认纯白时与写死等价，
 *     只有 .send 这种强调按钮换成蓝色。
 */
const BUTTON_FRAG_SOURCE = `
#ifdef GL_FRAGMENT_PRECISION_HIGH
precision highp float;
#else
precision mediump float;
#endif

uniform sampler2D u_image;
uniform vec2  u_resolution;     // 按钮尺寸（canvas 像素）
uniform vec2  u_textureSize;    // 背景裁剪纹理尺寸
uniform vec2  u_origin;         // 按钮左上角在纹理里的位置（纹理像素）
uniform vec2  u_size;           // 按钮尺寸（纹理像素）
uniform float u_borderRadius;
uniform float u_blurRadius;
uniform float u_tapLimit;
uniform float u_warp;
uniform float u_edgeIntensity;
uniform float u_rimIntensity;
uniform float u_baseIntensity;
uniform float u_edgeDistance;
uniform float u_rimDistance;
uniform float u_baseDistance;
uniform float u_cornerBoost;
uniform float u_rippleEffect;
uniform float u_tintOpacity;
uniform vec3  u_tintColor;      // 原库写死白→灰；纯白即等价
uniform float u_alpha;
uniform vec3  u_backdrop;       // 按钮背后那层面板的底色

varying vec2 v_texcoord;

float roundedRectDistance(vec2 coord, vec2 size, float radius) {
  vec2 center = size * 0.5;
  vec2 pixelCoord = coord * size;
  vec2 toCorner = abs(pixelCoord - center) - (center - radius);
  float outsideCorner = length(max(toCorner, 0.0));
  float insideCorner = min(max(toCorner.x, toCorner.y), 0.0);
  return (outsideCorner + insideCorner - radius);
}

float circleDistance(vec2 coord, vec2 size, float radius) {
  vec2 center = vec2(0.5, 0.5);
  vec2 pixelCoord = coord * size;
  vec2 centerPixel = center * size;
  float distFromCenter = length(pixelCoord - centerPixel);
  return distFromCenter - radius;
}

bool isPill(vec2 size, float radius) {
  float heightRatioDiff = abs(radius - size.y * 0.5);
  bool radiusMatchesHeight = heightRatioDiff < 2.0;
  bool isWiderThanTall = size.x > size.y + 4.0;
  return radiusMatchesHeight && isWiderThanTall;
}

bool isCircle(vec2 size, float radius) {
  float minDim = min(size.x, size.y);
  bool radiusMatchesMinDim = abs(radius - minDim * 0.5) < 1.0;
  bool isRoughlySquare = abs(size.x - size.y) < 4.0;
  return radiusMatchesMinDim && isRoughlySquare;
}

float pillDistance(vec2 coord, vec2 size, float radius) {
  vec2 center = size * 0.5;
  vec2 pixelCoord = coord * size;

  vec2 capsuleStart = vec2(radius, center.y);
  vec2 capsuleEnd = vec2(size.x - radius, center.y);
  vec2 capsuleAxis = capsuleEnd - capsuleStart;
  float capsuleLength = length(capsuleAxis);

  if (capsuleLength > 0.0) {
    vec2 toPoint = pixelCoord - capsuleStart;
    float t = clamp(dot(toPoint, capsuleAxis) / dot(capsuleAxis, capsuleAxis), 0.0, 1.0);
    vec2 closestPointOnAxis = capsuleStart + t * capsuleAxis;
    return length(pixelCoord - closestPointOnAxis) - radius;
  } else {
    return length(pixelCoord - center) - radius;
  }
}

void main() {
  vec2 coord = v_texcoord;

  // 按钮背后那一片背景在纹理里的位置（用于取三条色带）
  vec2 baseTextureCoord = (u_origin + coord * u_size) / u_textureSize;
  vec2 textureCoord = baseTextureCoord;

  float distFromEdgeShape;
  vec2 shapeNormal;

  if (isPill(u_resolution, u_borderRadius)) {
    distFromEdgeShape = -pillDistance(coord, u_resolution, u_borderRadius);

    vec2 center = vec2(0.5, 0.5);
    vec2 pixelCoord = coord * u_resolution;
    vec2 capsuleStart = vec2(u_borderRadius, center.y * u_resolution.y);
    vec2 capsuleEnd = vec2(u_resolution.x - u_borderRadius, center.y * u_resolution.y);
    vec2 capsuleAxis = capsuleEnd - capsuleStart;
    float capsuleLength = length(capsuleAxis);

    if (capsuleLength > 0.0) {
      vec2 toPoint = pixelCoord - capsuleStart;
      float t = clamp(dot(toPoint, capsuleAxis) / dot(capsuleAxis, capsuleAxis), 0.0, 1.0);
      vec2 closestPointOnAxis = capsuleStart + t * capsuleAxis;
      vec2 normalDir = pixelCoord - closestPointOnAxis;
      shapeNormal = length(normalDir) > 0.0 ? normalize(normalDir) : vec2(0.0, 1.0);
    } else {
      shapeNormal = normalize(coord - center);
    }
  } else if (isCircle(u_resolution, u_borderRadius)) {
    distFromEdgeShape = -circleDistance(coord, u_resolution, u_borderRadius);
    vec2 center = vec2(0.5, 0.5);
    shapeNormal = normalize(coord - center);
  } else {
    distFromEdgeShape = -roundedRectDistance(coord, u_resolution, u_borderRadius);
    vec2 center = vec2(0.5, 0.5);
    shapeNormal = normalize(coord - center);
  }
  distFromEdgeShape = max(distFromEdgeShape, 0.0);

  float distFromLeft = coord.x;
  float distFromRight = 1.0 - coord.x;
  float distFromTop = coord.y;
  float distFromBottom = 1.0 - coord.y;
  float distFromEdge = distFromEdgeShape / min(u_resolution.x, u_resolution.y);

  float normalizedDistance = distFromEdge * min(u_resolution.x, u_resolution.y);
  float baseIntensity = 1.0 - exp(-normalizedDistance * u_baseDistance);
  float edgeIntensity = exp(-normalizedDistance * u_edgeDistance);
  float rimIntensity = exp(-normalizedDistance * u_rimDistance);

  float baseComponent = u_warp > 0.5 ? baseIntensity * u_baseIntensity : 0.0;
  float totalIntensity = baseComponent + edgeIntensity * u_edgeIntensity + rimIntensity * u_rimIntensity;

  vec2 baseRefraction = shapeNormal * totalIntensity;

  float cornerProximityX = min(distFromLeft, distFromRight);
  float cornerProximityY = min(distFromTop, distFromBottom);
  float cornerDistance = max(cornerProximityX, cornerProximityY);
  float cornerNormalized = cornerDistance * min(u_resolution.x, u_resolution.y);

  float cornerBoost = exp(-cornerNormalized * 0.3) * u_cornerBoost;
  vec2 cornerRefraction = shapeNormal * cornerBoost;

  // 原库按钮的波纹频率是 30（容器是 25）
  vec2 perpendicular = vec2(-shapeNormal.y, shapeNormal.x);
  float rippleEffect = sin(distFromEdge * 30.0) * u_rippleEffect * rimIntensity;
  vec2 textureRefraction = perpendicular * rippleEffect;

  vec2 totalRefraction = baseRefraction + cornerRefraction + textureRefraction;
  textureCoord = baseTextureCoord + totalRefraction;

  // 高斯模糊：σ = blurRadius / 3，9×9 核（原库按钮的写法）
  vec4 color = vec4(0.0);
  vec2 texelSize = 1.0 / u_textureSize;
  float sigma = max(u_blurRadius / 3.0, 1e-3);
  vec2 blurStep = texelSize * sigma;

  float totalWeight = 0.0;

  for (float i = -4.0; i <= 4.0; i += 1.0) {
    for (float j = -4.0; j <= 4.0; j += 1.0) {
      float distance = length(vec2(i, j));
      if (distance > 4.0) continue;
      if (distance > u_tapLimit) continue;

      float weight = exp(-(distance * distance) / (2.0 * sigma * sigma));

      vec2 offset = vec2(i, j) * blurStep;
      color += texture2D(u_image, textureCoord + offset) * weight;
      totalWeight += weight;
    }
  }

  color /= totalWeight;

  // 按钮背后是 CSS 玻璃面板：先把面板底色合进来（粒子层是透明底的预乘 alpha）
  vec3 base = color.rgb + u_backdrop * (1.0 - color.a);

  float gradientPosition = coord.y;

  // 第一层：写死的「白 → 灰」竖直渐变，权重 tintOpacity * 0.7
  vec3 gradientTint = mix(u_tintColor, u_tintColor * 0.7, gradientPosition);
  vec3 tintedColor = mix(base, gradientTint, u_tintOpacity * 0.7);

  // 第二层：沿按钮竖直方向取三条色带再插值，权重 tintOpacity * 0.4
  // （纹理是预乘贴图，取到的是 over 之后的实际观感色，与底下 base 同一套坐标）
  vec2 centerTex = baseTextureCoord + vec2(0.5, 0.5) * u_size / u_textureSize;
  float spanY = u_size.y / u_textureSize.y * 0.4;
  vec4 topTexel = texture2D(u_image, clamp(vec2(centerTex.x, centerTex.y - spanY), 0.0, 1.0));
  vec4 midTexel = texture2D(u_image, centerTex);
  vec4 bottomTexel = texture2D(u_image, clamp(vec2(centerTex.x, centerTex.y + spanY), 0.0, 1.0));
  vec3 topSample = clamp(topTexel.rgb + u_backdrop * (1.0 - topTexel.a), 0.0, 1.0);
  vec3 midSample = clamp(midTexel.rgb + u_backdrop * (1.0 - midTexel.a), 0.0, 1.0);
  vec3 bottomSample = clamp(bottomTexel.rgb + u_backdrop * (1.0 - bottomTexel.a), 0.0, 1.0);

  vec3 sampledGradient;
  if (gradientPosition < 0.1) {
    sampledGradient = topSample;
  } else if (gradientPosition > 0.9) {
    sampledGradient = bottomSample;
  } else {
    float t = (gradientPosition - 0.1) / 0.8;
    sampledGradient = t < 0.5
      ? mix(topSample, midSample, t * 2.0)
      : mix(midSample, bottomSample, (t - 0.5) * 2.0);
  }
  vec3 secondTinted = mix(tintedColor, sampledGradient, u_tintOpacity * 0.4);

  // 第三层：上亮下暗的亮度斜坡（原库写死 1.08 / 0.92）
  vec3 buttonGradient = mix(vec3(1.08), vec3(0.92), gradientPosition);
  vec3 finalColor = secondTinted * buttonGradient;

  // 形状遮罩
  float maskDistance;
  if (isPill(u_resolution, u_borderRadius)) {
    maskDistance = pillDistance(coord, u_resolution, u_borderRadius);
  } else if (isCircle(u_resolution, u_borderRadius)) {
    maskDistance = circleDistance(coord, u_resolution, u_borderRadius);
  } else {
    maskDistance = roundedRectDistance(coord, u_resolution, u_borderRadius);
  }
  float mask = 1.0 - smoothstep(-1.0, 1.0, maskDistance);

  // canvas 是 premultiplied alpha，跟着乘 mask 才不会在描边处发亮
  float alpha = mask * u_alpha;
  gl_FragColor = vec4(finalColor * alpha, alpha);
}
`

/**
 * 高斯核截断半径（3σ 原则）：blurRadius=1 时 σ=0.5，只剩 21 个 tap，
 * 被跳过的那些权重都 < 1e-3，对归一化后的颜色没有可测影响。
 * 原版硬编码 6.0，是因为它只在静态快照上跑一次，不在乎成本。
 */
function tapLimitFor(blurRadius) {
  const sigma = Math.max(blurRadius, 0.001) / 2
  return Math.min(6, Math.ceil(3 * sigma))
}

/** #rrggbb → 0..1 的 rgb，用于在着色器里合成页面底色 */
function hexToRgb(hex) {
  const m = /^#?([0-9a-f]{6})$/i.exec(String(hex).trim())
  if (!m) return [0, 0, 0]
  const n = parseInt(m[1], 16)
  return [((n >> 16) & 255) / 255, ((n >> 8) & 255) / 255, (n & 255) / 255]
}

function compile(gl, type, source) {
  const shader = gl.createShader(type)
  gl.shaderSource(shader, source)
  gl.compileShader(shader)
  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
    console.error('[liquid-glass] 着色器编译失败:', gl.getShaderInfoLog(shader))
    return null
  }
  return shader
}

function link(gl, fragSource = FRAG_SOURCE) {
  const vs = compile(gl, gl.VERTEX_SHADER, VERT_SOURCE)
  const fs = compile(gl, gl.FRAGMENT_SHADER, fragSource)
  if (!vs || !fs) return null

  const program = gl.createProgram()
  gl.attachShader(program, vs)
  gl.attachShader(program, fs)
  gl.linkProgram(program)

  if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
    console.error('[liquid-glass] 程序链接失败:', gl.getProgramInfoLog(program))
    return null
  }
  return program
}

/**
 * 一块面板的玻璃。
 * @typedef {{ element: Element, radius: number }} Surface
 */
export class LiquidGlassLayer {
  /**
   * @param {object} options
   * @param {HTMLCanvasElement} options.canvas   负责承载整屏玻璃的 canvas
   * @param {() => HTMLCanvasElement | null} options.source  背景帧来源（粒子 canvas）
   * @param {object} [options.params]            玻璃参数，默认 myconfig 预设
   * @param {number} [options.pixelRatio]        canvas 像素比（默认 1，与原库一致）
   * @param {number} [options.fps]               重绘上限（默认 30）
   * @param {string} [options.backdrop]          页面底色，用于合成透明底粒子层
   * @param {'panel'|'button'} [options.shader]   用哪套片元着色器（默认面板版）
   */
  constructor({
    canvas,
    source,
    params = LIQUID_GLASS_PRESET,
    pixelRatio = 1,
    fps = 30,
    backdrop = '#030509',
    shader = 'panel',
  }) {
    this.canvas = canvas
    this.source = source
    this.params = { ...LIQUID_GLASS_PRESET, ...params }
    this.pixelRatio = pixelRatio
    this.minInterval = 1000 / Math.max(fps, 1)
    this.backdrop = hexToRgb(backdrop)
    /** 按钮版着色器的染色/模糊档位与原库 button.js 一致 */
    this.shader = shader === 'button' ? 'button' : 'panel'
    this.fragmentSource = this.shader === 'button' ? BUTTON_FRAG_SOURCE : FRAG_SOURCE
    /** 默认染色目标色；单个 surface 可以用 --lg-btn-tint-color 覆盖 */
    this.tintRgb = hexToRgb(this.params.tintColor || '#ffffff')

    /** @type {Set<Surface>} */
    this.surfaces = new Set()
    this.running = false
    this.raf = 0
    this.lastDraw = 0
    this.failCount = 0
    /** 连续多少帧拿不到背景帧（用来在粒子层缺席时退回 CSS 玻璃） */
    this.missCount = 0

    this.gl = null
    this.program = null
    this.uniforms = {}
    this.texture = null
    /** 上传纹理用的中转画布（裁剪区先拷到这里，见 draw()） */
    this.scratchCanvas = null
    this.scratchCtx = null

    this._onLost = (event) => {
      event.preventDefault()
      this.stop()
    }
    this._onRestored = () => {
      this.setup()
      this.start()
    }
  }

  /**
   * 接管一块面板/按钮：打上 data-liquid，玻璃由 canvas 负责画。
   *
   * 染色刻度写在 `.tab.glass-btn[data-liquid]` 这类选择器上，属性必须在
   * getComputedStyle 之前加上 —— 晚一步就读到空值，发送键永远不变蓝。
   */
  attach(element, options = {}) {
    if (!element || this.failCount > 3) return null

    element.dataset.liquid = 'on'
    const style = getComputedStyle(element)

    const surface = {
      element,
      radius: options.radius ?? (parseFloat(style.borderTopLeftRadius) || 0),
      rect: null,
      tintOpacity: null,
      tintRgb: null,
      clippers: this.collectClippers(element),
    }
    this.readTint(surface, style)
    this.surfaces.add(surface)
    return surface
  }

  /**
   * 从 CSS 变量读染色：`--lg-btn-tint`（0..1）与 `--lg-btn-tint-color`（#rrggbb）。
   *
   * 没写就留 null，绘制时退回预设值 —— 「所有按钮默认按预设渲染」这条约束
   * 因此是 CSS 里的默认行为，而不是每个按钮各自写死一档。
   */
  readTint(surface, style = getComputedStyle(surface.element)) {
    const tint = Number.parseFloat(style.getPropertyValue('--lg-btn-tint'))
    surface.tintOpacity = Number.isFinite(tint) ? Math.min(1, Math.max(0, tint)) : null

    const color = style.getPropertyValue('--lg-btn-tint-color').trim().replace(/^#/, '')
    surface.tintRgb = /^[0-9a-f]{6}$/i.test(color) ? hexToRgb('#' + color) : null
  }

  /** 按钮换了 class（选中态、禁用态）之后重读染色与裁剪祖先 */
  refresh(surface) {
    if (!surface || !surface.element) return
    const style = getComputedStyle(surface.element)
    this.readTint(surface, style)
    surface.clippers = this.collectClippers(surface.element)
  }

  /**
   * 收集会剪裁按钮的祖先（会话列表的 overflow:auto、面板的 overflow:hidden）。
   * draw() 每帧按这些矩形求交交给 SCISSOR_TEST，
   * 免得按钮滚出列表之后玻璃还浮在外面。
   */
  collectClippers(element) {
    const out = []
    const stop = this.canvas ? this.canvas.parentElement : null
    let node = element.parentElement
    while (node && node !== stop) {
      const style = getComputedStyle(node)
      if (/auto|scroll|hidden|clip/.test(style.overflowX + style.overflowY)) {
        out.push(node)
      }
      node = node.parentElement
    }
    return out
  }

  /**
   * 按钮版着色器的 u_backdrop：按钮背后那层面板的实际底色。
   *
   * 面板没走 WebGL，它的颜色是「粒子层 + 白 10% 渐变」算出来的，纹理里没有。
   * 这里按同样的算法合成一个近似值：页面底色往白推 --lg-tint 那么多；
   * 乘 0.95 是因为面板的竖直渐变在 0.72..1.55 之间来回，取接近均值的位置。
   * canvas 的直接父元素不是面板时（restore 药丸是自渲染的），退回页面底色。
   */
  panelBackdrop() {
    const panel = this.canvas ? this.canvas.parentElement : null
    if (panel) {
      // 容器可以自己声明底色（弹窗比面板亮一档，遮在弹窗上的按钮不能按页面底色算）
      const declared = getComputedStyle(panel).getPropertyValue('--glass-backdrop').trim()
      if (/^#?[0-9a-f]{6}$/i.test(declared)) return hexToRgb(declared)
    }
    let tint = 0.1
    if (panel) {
      const value = Number.parseFloat(getComputedStyle(panel).getPropertyValue('--lg-tint'))
      if (Number.isFinite(value)) tint = Math.min(1, Math.max(0, value))
    }
    const k = tint * 0.95
    return [
      this.backdrop[0] * (1 - k) + k,
      this.backdrop[1] * (1 - k) + k,
      this.backdrop[2] * (1 - k) + k,
    ]
  }

  detach(element) {
    for (const surface of this.surfaces) {
      if (surface.element === element) {
        this.surfaces.delete(surface)
        delete element.dataset.liquid
      }
    }
  }

  setup() {
    const canvas = this.canvas
    if (!canvas) return false

    const gl =
      canvas.getContext('webgl', {
        alpha: true,
        antialias: false,
        depth: false,
        premultipliedAlpha: true,
        preserveDrawingBuffer: false,
      }) || null

    if (!gl) {
      console.warn('[liquid-glass] WebGL 不可用，回退到 CSS 玻璃')
      this.failCount = 9
      this.clearMarks()
      return false
    }

    this.gl = gl
    canvas.addEventListener('webglcontextlost', this._onLost, false)
    canvas.addEventListener('webglcontextrestored', this._onRestored, false)

    const program = link(gl, this.fragmentSource)
    if (!program) {
      this.failCount = 9
      this.clearMarks()
      return false
    }
    this.program = program
    gl.useProgram(program)

    // 全屏三角带来的两个 buffer
    this.positionBuffer = gl.createBuffer()
    gl.bindBuffer(gl.ARRAY_BUFFER, this.positionBuffer)
    gl.bufferData(
      gl.ARRAY_BUFFER,
      new Float32Array([-1, -1, 1, -1, -1, 1, -1, 1, 1, -1, 1, 1]),
      gl.STATIC_DRAW,
    )

    this.texcoordBuffer = gl.createBuffer()
    gl.bindBuffer(gl.ARRAY_BUFFER, this.texcoordBuffer)
    gl.bufferData(
      gl.ARRAY_BUFFER,
      new Float32Array([0, 1, 1, 1, 0, 0, 0, 0, 1, 1, 1, 0]),
      gl.STATIC_DRAW,
    )

    const positionLoc = gl.getAttribLocation(program, 'a_position')
    const texcoordLoc = gl.getAttribLocation(program, 'a_texcoord')

    gl.bindBuffer(gl.ARRAY_BUFFER, this.positionBuffer)
    gl.enableVertexAttribArray(positionLoc)
    gl.vertexAttribPointer(positionLoc, 2, gl.FLOAT, false, 0, 0)

    gl.bindBuffer(gl.ARRAY_BUFFER, this.texcoordBuffer)
    gl.enableVertexAttribArray(texcoordLoc)
    gl.vertexAttribPointer(texcoordLoc, 2, gl.FLOAT, false, 0, 0)

    const names = [
      'u_image',
      'u_resolution',
      'u_textureSize',
      'u_origin',
      'u_size',
      'u_borderRadius',
      'u_blurRadius',
      'u_tapLimit',
      'u_warp',
      'u_edgeIntensity',
      'u_rimIntensity',
      'u_baseIntensity',
      'u_edgeDistance',
      'u_rimDistance',
      'u_baseDistance',
      'u_cornerBoost',
      'u_rippleEffect',
      'u_tintOpacity',
      'u_tintColor',
      'u_alpha',
      'u_backdrop',
    ]
    /** @type {Record<string, WebGLUniformLocation | null>} */
    this.uniforms = {}
    names.forEach((name) => {
      this.uniforms[name] = gl.getUniformLocation(program, name)
    })

    this.texture = gl.createTexture()
    gl.bindTexture(gl.TEXTURE_2D, this.texture)
    gl.parametrizeTexture && gl.parametrizeTexture()
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR)
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR)
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE)
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE)

    // 大半径磨砂用的第二张纹理：把粒子帧缩到 1/4 再用 2D canvas 的 Skia blur
    // 预模糊（见 draw() 里的说明），着色器只取 1 个 tap。
    this.blurTexture = gl.createTexture()
    gl.bindTexture(gl.TEXTURE_2D, this.blurTexture)
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR)
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR)
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE)
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE)
    this.blurCanvas = null
    this.blurCtx = null

    gl.activeTexture(gl.TEXTURE0)
    gl.uniform1i(this.uniforms.u_image, 0)

    // 整块面板共享的参数
    const p = this.params
    gl.uniform1f(this.uniforms.u_blurRadius, p.blurRadius)
    // 按钮版照原库固定 9×9、半径 4（σ = blurRadius/3，3σ 也就到 3，库里不截断）
    gl.uniform1f(
      this.uniforms.u_tapLimit,
      this.shader === 'button' ? 4 : tapLimitFor(p.blurRadius),
    )
    gl.uniform1f(this.uniforms.u_warp, p.warp ? 1 : 0)
    gl.uniform1f(this.uniforms.u_edgeIntensity, p.edgeIntensity)
    gl.uniform1f(this.uniforms.u_rimIntensity, p.rimIntensity)
    gl.uniform1f(this.uniforms.u_baseIntensity, p.baseIntensity)
    gl.uniform1f(this.uniforms.u_edgeDistance, p.edgeDistance)
    gl.uniform1f(this.uniforms.u_rimDistance, p.rimDistance)
    gl.uniform1f(this.uniforms.u_baseDistance, p.baseDistance)
    gl.uniform1f(this.uniforms.u_cornerBoost, p.cornerBoost)
    gl.uniform1f(this.uniforms.u_rippleEffect, p.rippleEffect)
    gl.uniform1f(this.uniforms.u_tintOpacity, p.tintOpacity)
    gl.uniform3f(this.uniforms.u_tintColor, ...hexToRgb(p.tintColor || '#ffffff'))
    gl.uniform3f(this.uniforms.u_backdrop, ...(this.shader === 'button' ? this.panelBackdrop() : this.backdrop))

    gl.disable(gl.DEPTH_TEST)
    gl.disable(gl.BLEND)
    return true
  }

  clearMarks() {
    for (const surface of this.surfaces) {
      delete surface.element.dataset.liquid
    }
  }

  start() {
    if (this.running) return
    if (!this.gl && !this.setup()) return
    this.running = true
    this.lastDraw = 0
    const tick = (time) => {
      if (!this.running) return
      this.raf = requestAnimationFrame(tick)
      if (time - this.lastDraw < this.minInterval) return
      this.lastDraw = time
      try {
        this.draw()
      } catch (error) {
        // 画到一半炸了（上下文丢了、纹理尺寸非法……）：别再每帧刷屏，
        // 直接把标记还回去让 CSS 玻璃接手
        console.warn('[liquid-glass] 绘制失败，退回 CSS 玻璃', error)
        this.failCount = 9
        this.clearMarks()
        this.stop()
      }
    }
    this.raf = requestAnimationFrame(tick)
  }

  stop() {
    this.running = false
    if (this.raf) cancelAnimationFrame(this.raf)
    this.raf = 0
  }

  destroy() {
    this.stop()
    this.clearMarks()
    this.surfaces.clear()
    if (this.canvas) {
      this.canvas.removeEventListener('webglcontextlost', this._onLost)
      this.canvas.removeEventListener('webglcontextrestored', this._onRestored)
    }
    const gl = this.gl
    if (gl) {
      if (this.texture) gl.deleteTexture(this.texture)
      if (this.positionBuffer) gl.deleteBuffer(this.positionBuffer)
      if (this.texcoordBuffer) gl.deleteBuffer(this.texcoordBuffer)
      // 显式丢掉上下文：右栏两张卡片是 v-if 的，来回开合会攒下一堆 GL 上下文，
      // 撞上浏览器上限（约 16 个）之后新 canvas 就拿不到上下文了，
      // 那会直接掉回 CSS 玻璃。
      const lose = gl.getExtension('WEBGL_lose_context')
      if (lose) lose.loseContext()
    }
    this.gl = null
    this.program = null
    this.texture = null
  }

  /**
   * 按 canvas 自己的 CSS 盒子同步像素尺寸。
   * 早期版本这块玻璃铺满整屏，所以直接用 window.innerWidth；
   * 现在它只铺满一块面板（按钮玻璃），必须看自己那块。
   */
  syncCanvasSize() {
    const canvas = this.canvas
    if (!canvas) return false
    const ratio = this.pixelRatio
    const cssWidth = canvas.clientWidth || canvas.getBoundingClientRect().width
    const cssHeight = canvas.clientHeight || canvas.getBoundingClientRect().height
    const width = Math.max(1, Math.round(cssWidth * ratio))
    const height = Math.max(1, Math.round(cssHeight * ratio))
    if (canvas.width !== width || canvas.height !== height) {
      canvas.width = width
      canvas.height = height
      return true
    }
    return false
  }

  draw() {
    const gl = this.gl
    const canvas = this.canvas
    if (!gl || !canvas) return

    const source = this.source()
    if (!source || !source.width || !source.height) {
      // 背景帧一直没有（粒子层没起来）：玻璃没有可折射的东西，
      // 这时候按钮的 CSS 底色已经被关掉了，必须把标记还回去，否则按钮变透明块
      this.missCount += 1
      if (this.missCount > 30) {
        this.failCount = 9
        this.clearMarks()
        this.stop()
      }
      return
    }
    this.missCount = 0
    if (!this.surfaces.size) return

    // canvas 的 CSS 盒子 = 这块面板；玻璃层只在面板内部画按钮
    const cbox = canvas.getBoundingClientRect()
    if (cbox.width < 2 || cbox.height < 2) return

    const ratio = this.pixelRatio
    this.syncCanvasSize()

    // 纹理换算：粒子 canvas 的 CSS 尺寸不一定等于视口（容器带 min-width:1200px，
    // 会把 fixed 层撑大并向右下溢出），必须用 canvas 自己的盒子把「屏幕像素」
    // 换算成「纹理像素」。
    const sbox = source.getBoundingClientRect()
    const boxW = sbox.width || source.clientWidth || source.width
    const boxH = sbox.height || source.clientHeight || source.height
    const sx = source.width / Math.max(boxW, 1)
    const sy = source.height / Math.max(boxH, 1)

    // 面板淡出/收起时，玻璃得跟着淡：玻璃画在 canvas 上，不吃祖先的 opacity
    const panel = canvas.parentElement || canvas
    const panelOpacity = Number(getComputedStyle(panel).opacity)
    const fade = Number.isFinite(panelOpacity) ? Math.min(1, Math.max(0, panelOpacity)) : 1

    /** 裁剪祖先的盒子每帧只量一次（多个按钮共享同一个列表容器） */
    const clipCache = new Map()
    const clipBox = (element) => {
      let box = clipCache.get(element)
      if (!box) {
        box = element.getBoundingClientRect()
        clipCache.set(element, box)
      }
      return box
    }

    // 第一遍：挑出这一帧真正要画的按钮，并算出它们的外包框。
    // 上传只覆盖这个外包框 —— 按钮只看得见自己脚下的背景，
    // 没必要为整块面板每帧搬一次像素（面板越大越亏）。
    const draws = []
    let minX = Infinity
    let minY = Infinity
    let maxX = -Infinity
    let maxY = -Infinity

    for (const surface of this.surfaces) {
      const element = surface.element
      if (!element.isConnected) continue
      // visibility:hidden（右栏收起）和 opacity:0 的按钮不用画
      if (
        element.checkVisibility &&
        !element.checkVisibility({ opacityProperty: true, visibilityProperty: true })
      ) {
        continue
      }

      const rect = element.getBoundingClientRect()
      if (rect.width < 2 || rect.height < 2) continue
      if (
        rect.right <= cbox.left ||
        rect.left >= cbox.right ||
        rect.bottom <= cbox.top ||
        rect.top >= cbox.bottom
      ) {
        continue
      }

      const ownOpacity = Number(getComputedStyle(element).opacity)
      const alpha = fade * (Number.isFinite(ownOpacity) ? Math.min(1, Math.max(0, ownOpacity)) : 1)
      if (alpha <= 0.01) continue

      // 和 CSS 一样按滚动容器裁剪：滚出列表的按钮不能留下幽灵玻璃
      let clipL = Math.max(rect.left, cbox.left)
      let clipT = Math.max(rect.top, cbox.top)
      let clipR = Math.min(rect.right, cbox.right)
      let clipB = Math.min(rect.bottom, cbox.bottom)
      for (const clipper of surface.clippers) {
        if (!clipper.isConnected) continue
        const box = clipBox(clipper)
        clipL = Math.max(clipL, box.left)
        clipT = Math.max(clipT, box.top)
        clipR = Math.min(clipR, box.right)
        clipB = Math.min(clipB, box.bottom)
      }
      if (clipR - clipL < 1 || clipB - clipT < 1) continue

      draws.push({ surface, rect, alpha, clipL, clipT, clipR, clipB })

      // 外包框按按钮自己的盒子算（不按裁剪后的可见部分），
      // UV 原点因此不会出现负数
      const bx0 = Math.max(rect.left, cbox.left)
      const by0 = Math.max(rect.top, cbox.top)
      const bx1 = Math.min(rect.right, cbox.right)
      const by1 = Math.min(rect.bottom, cbox.bottom)
      if (bx0 < minX) minX = bx0
      if (by0 < minY) minY = by0
      if (bx1 > maxX) maxX = bx1
      if (by1 > maxY) maxY = by1
    }

    if (!draws.length) {
      // 没有按钮要画：清空画布，别让上一帧的玻璃留在屏上
      gl.viewport(0, 0, canvas.width, canvas.height)
      gl.clearColor(0, 0, 0, 0)
      gl.clear(gl.COLOR_BUFFER_BIT)
      return
    }

    // 外框在屏幕像素 → 粒子纹理像素（像素整数、夹在源边界内）。
    // 外扩一圈：模糊采样要取到按钮外面的像素，紧贴边缘会采到 clamp 的同一行，
    // 按钮边上会出现一道"抽色"。
    const PAD = 12
    const wantX = (minX - PAD - sbox.left) * sx
    const wantY = (minY - PAD - sbox.top) * sy
    const cropX = Math.max(0, Math.min(Math.round(wantX), source.width - 1))
    const cropY = Math.max(0, Math.min(Math.round(wantY), source.height - 1))
    const cropW = Math.max(
      1,
      Math.min(Math.round((maxX - minX + PAD * 2) * sx), source.width - cropX),
    )
    const cropH = Math.max(
      1,
      Math.min(Math.round((maxY - minY + PAD * 2) * sy), source.height - cropY),
    )
    // 裁到源边界内之后坐标系整体平移了，UV 要补回来，否则玻璃与背景错位
    const offX = wantX - cropX
    const offY = wantY - cropY

    gl.bindTexture(gl.TEXTURE_2D, this.texture)
    gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false)
    // 粒子层是「预乘 alpha」的透明画布。默认 UNPACK_PREMULTIPLY_ALPHA_WEBGL=false
    // 会让浏览器把 canvas 反预乘：alpha≈0.01 的暗尘被 rgb/alpha 放大成接近 1，
    // 于是玻璃背后整片网线变成白雾（这一条曾经把面板玻璃洗成灰白）。
    // 打开它 = 按原样（预乘）上传，着色器里 color.rgb + backdrop*(1-alpha)
    // 正好就是正确的 over 合成，模糊也在预乘空间里做，不会被量化噪声放大。
    gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, true)
    // WebGL 的 texImage2D 没有「从 canvas 里裁一块」的重载（十参那版只吃
    // ArrayBufferView，拿 canvas 去调会直接 TypeError）。所以先把裁剪区
    // 复制进一张 2D 画布，再整张上传 —— canvas→canvas 的 drawImage 在
    // 浏览器里是 GPU 侧的 blit，比每帧整张粒子层（1600×1000）上传便宜一个量级。
    let scratch = this.scratchCanvas
    if (!scratch) {
      scratch = this.scratchCanvas = document.createElement('canvas')
      this.scratchCtx = scratch.getContext('2d', { alpha: true })
    }
    if (scratch.width !== cropW || scratch.height !== cropH) {
      scratch.width = cropW
      scratch.height = cropH
    }
    const ctx = this.scratchCtx
    ctx.clearRect(0, 0, cropW, cropH)
    ctx.drawImage(source, cropX, cropY, cropW, cropH, 0, 0, cropW, cropH)
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, scratch)


    gl.viewport(0, 0, canvas.width, canvas.height)
    gl.clearColor(0, 0, 0, 0)
    gl.clear(gl.COLOR_BUFFER_BIT)

    // 每块按钮一个 viewport，圆角由着色器算，外面再叠一层滚动裁剪
    gl.enable(gl.SCISSOR_TEST)
    for (const item of draws) {
      const { surface, rect, alpha, clipL, clipT, clipR, clipB } = item

      const w = Math.max(1, Math.round(rect.width * ratio))
      const h = Math.max(1, Math.round(rect.height * ratio))

      // WebGL 的 viewport 原点在左下角
      gl.viewport(
        Math.round((rect.left - cbox.left) * ratio),
        Math.round(canvas.height - (rect.top - cbox.top + rect.height) * ratio),
        w,
        h,
      )
      gl.scissor(
        Math.round((clipL - cbox.left) * ratio),
        Math.round(canvas.height - (clipT - cbox.top + (clipB - clipT)) * ratio),
        Math.max(1, Math.round((clipR - clipL) * ratio)),
        Math.max(1, Math.round((clipB - clipT) * ratio)),
      )

      gl.uniform2f(this.uniforms.u_textureSize, cropW, cropH)
      gl.uniform2f(this.uniforms.u_resolution, w, h)
      // 999px 这种写法要夹到半高半宽，否则 roundedRectDistance 处处为负、折射消失
      const radius = Math.min(surface.radius, Math.min(rect.width, rect.height) / 2)
      gl.uniform1f(this.uniforms.u_borderRadius, radius * ratio)
      gl.uniform1f(this.uniforms.u_alpha, alpha)

      // 每类按钮的染色刻度（.tab 浅、.send 深蓝），由 CSS 变量给出
      gl.uniform1f(
        this.uniforms.u_tintOpacity,
        surface.tintOpacity === null ? this.params.tintOpacity : surface.tintOpacity,
      )
      gl.uniform3f(this.uniforms.u_tintColor, ...(surface.tintRgb || this.tintRgb))

      gl.uniform2f(
        this.uniforms.u_origin,
        // + PAD：纹理左上角被外扩过，按钮相对它的偏移要补回来
        (rect.left - minX + PAD) * sx + offX,
        (rect.top - minY + PAD) * sy + offY,
      )
      gl.uniform2f(this.uniforms.u_size, rect.width * sx, rect.height * sy)

      gl.drawArrays(gl.TRIANGLES, 0, 6)
    }
    gl.disable(gl.SCISSOR_TEST)
  }
}

export default LiquidGlassLayer