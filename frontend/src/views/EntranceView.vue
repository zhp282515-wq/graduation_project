<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import Icon from '../components/ui/Icon.vue'
import seal from '../assets/school-seal.svg'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const registering = computed(() => route.name === 'register')
const hasSwitchedMode = ref(false)
const username = ref('')
const password = ref('')
const confirmation = ref('')
const showPassword = ref(false)
const submitting = ref(false)
const error = ref('')
const fieldError = ref('')
const invalidField = ref('')
const passwordInput = ref(null)
const confirmationInput = ref(null)
const nameInput = ref(null)
const formArea = ref(null)
const root = ref(null)
const example = ref(0)
const sourceOpen = ref(false)
const selectedNode = ref(0)
const networkError = ref('')
const pageHidden = ref(false)
let observer
let frame = 0
let reduced = false
const examples = [
  { question: '校园里的办事流程，应该从哪里找起？', answer: '从一个具体问题开始。饭饭会结合可访问的校园文档组织回答，并展示检索过程和文档来源。', excerpt: '输入事项名称或关键词，查阅相关文档；在回答的引用处核对文档名、章节和原文。' },
  { question: '这段回答的依据，可以在哪里核对？', answer: '点击回答旁的引用，查看对应的文档片段。你也可以打开来源文档，继续阅读上下文。', excerpt: '引用保留文档名称、章节、页码或分片信息；可从来源面板定位到对应文档片段。' },
  { question: '很多份校园资料，怎样看清它们的联系？', answer: '在知识星图里，文档与分片形成可探索的空间。选择一颗星，查看它的内容与所属文档。', excerpt: '星体对应知识分片，星链连接文档内的顺序；语义连线用于呈现内容之间的相似关联。' },
]
const current = computed(() => examples[example.value])
const nodes = [
  { x: 372, y: 202, title: '文档', text: '一份文档，构成知识的一处来路。' },
  { x: 469, y: 291, title: '分片', text: '选择分片，阅读内容与所属文档。' },
  { x: 278, y: 310, title: '引用', text: '从回答回到依据，核对来源与上下文。' },
  { x: 540, y: 169, title: '关联', text: '以语义相似性发现内容之间的联系。' },
]
const satellites = Array.from({ length: 32 }, (_, i) => ({
  x: 385 + Math.cos(i * 2.399) * (72 + (i % 7) * 23),
  y: 250 + Math.sin(i * 2.399) * (45 + (i % 5) * 24),
  r: i % 5 === 0 ? 2.5 : 1.3,
}))

watch(registering, () => {
  hasSwitchedMode.value = true
  password.value = ''; confirmation.value = ''; showPassword.value = false
  error.value = ''; fieldError.value = ''; invalidField.value = ''
})

async function switchMode(mode) {
  if (submitting.value) return
  await router.push({ path: mode === 'register' ? '/register' : '/login', query: route.query })
}
function focusForm() {
  formArea.value?.scrollIntoView({ behavior: reduced ? 'instant' : 'smooth', block: 'center' })
  nameInput.value?.focus({ preventScroll: true })
}
async function submit() {
  if (submitting.value) return
  error.value = ''; fieldError.value = ''; invalidField.value = ''
  if (!/^[A-Za-z0-9_-]{3,32}$/.test(username.value.trim())) {
    invalidField.value = 'username'; fieldError.value = '用户名需为3–32位字母、数字、下划线或连字符'; nameInput.value?.focus(); return
  }
  if (password.value.length < 8 || password.value.length > 128) { invalidField.value = 'password'; fieldError.value = '密码需为8–128个字符'; passwordInput.value?.focus(); return }
  if (registering.value && password.value !== confirmation.value) { invalidField.value = 'confirmation'; fieldError.value = '两次输入的密码不一致'; confirmationInput.value?.focus(); return }
  submitting.value = true
  try {
    await auth.authenticate(registering.value ? 'register' : 'login', { username: username.value.trim(), password: password.value })
    const target = route.query.redirect
    const safe = typeof target === 'string' && target.startsWith('/') && !target.startsWith('//') && !target.includes('\\') && !/^\/(login|register|password)(\/|\?|$)/.test(target)
    await router.replace(auth.user.must_change_password ? '/password' : safe ? target : '/inquiry')
  } catch (err) { error.value = err.message || '暂时无法连接，请稍后重试' }
  finally { submitting.value = false }
}
async function leaveAccount() {
  try { await auth.logout() } catch (err) { error.value = err.message || '退出未完成，请重试' }
}
async function retryIdentity() {
  networkError.value = ''
  try { await auth.restore() } catch { networkError.value = '暂时无法连接服务，可稍后重新尝试登录。' }
}
function updateScroll() {
  frame = 0
  if (!root.value || reduced) return
  const height = window.innerHeight
  for (const section of root.value.querySelectorAll('[data-depth]')) {
    const bounds = section.getBoundingClientRect()
    if (bounds.bottom > 0 && bounds.top < height) {
      const progress = Math.max(-1, Math.min(1, (height / 2 - bounds.top - bounds.height / 2) / height))
      section.style.setProperty('--drift', `${progress * 28}px`)
    }
  }
}
function onScroll() { if (!frame && !document.hidden) frame = requestAnimationFrame(updateScroll) }
function onVisibility() { pageHidden.value = document.hidden; if (document.hidden) cancelAnimationFrame(frame); frame = 0; if (!document.hidden) onScroll() }
onMounted(() => {
  reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches
  observer = new IntersectionObserver((entries) => entries.forEach((entry) => {
    entry.target.classList.toggle('is-visible', entry.isIntersecting)
    if (entry.isIntersecting) {
      entry.target.classList.add('is-seen')
      if (!entry.target.classList.contains('constellation-preview')) observer.unobserve(entry.target)
    }
  }), { threshold: 0.12 })
  root.value.querySelectorAll('[data-reveal]').forEach((element) => observer.observe(element))
  window.addEventListener('scroll', onScroll, { passive: true })
  document.addEventListener('visibilitychange', onVisibility)
  retryIdentity()
  updateScroll()
})
onBeforeUnmount(() => {
  observer?.disconnect(); cancelAnimationFrame(frame)
  window.removeEventListener('scroll', onScroll)
  document.removeEventListener('visibilitychange', onVisibility)
})
</script>

<template>
  <div id="entry-start" ref="root" class="entrance" :class="{ 'is-paused': pageHidden, 'has-switched-mode': hasSwitchedMode }">
    <a href="#access" class="skip-entry">跳到登录表单</a>
    <header class="entry-header">
      <RouterLink to="/" class="entry-brand" aria-label="江西师范大学，返回首页">
        <svg class="entry-brand-seal" viewBox="205 80 390 390" aria-hidden="true" focusable="false">
          <image :href="seal" width="794" height="659" />
        </svg>
        <svg class="entry-brand-wordmark" viewBox="60 500 700 145" aria-hidden="true" focusable="false">
          <image :href="seal" width="794" height="659" />
        </svg>
      </RouterLink>
      <nav aria-label="产品介绍"><a href="#conversation">问有所答</a><a href="#evidence">答有所据</a><a href="#constellation">知识成图</a></nav>
      <a v-if="auth.user" class="header-action" href="/inquiry" @click.prevent="router.push('/inquiry')">进入问学 <Icon name="arrowRight" :size="16" /></a>
      <button v-else class="header-action" type="button" @click="focusForm">{{ registering ? '创建账号' : '开始问学' }} <Icon name="arrowRight" :size="16" /></button>
    </header>

    <main>
      <section class="entry-hero" aria-labelledby="entry-title">
        <div class="hero-story">
          <span class="hero-glyph" aria-hidden="true">问</span>
          <div class="hero-edition"><span>饭饭 · 校园智能体</span><span>知识，从这里连接</span></div>
          <h1 id="entry-title">从校园一问，<br />走进<span class="title-orbit">知识星图<svg viewBox="0 0 360 27" aria-hidden="true"><path d="M3 21 C95 1 245 2 355 12" /></svg></span>。</h1>
          <p class="hero-description">让零散的校园资料，成为可以对话的知识。<br />向饭饭提问，沿着引用找到依据，在星图里发现联系。</p>
          <div class="hero-proof" aria-label="从提问到来源的示例">
            <span class="proof-ask"><Icon name="inquiry" :size="19" /> 一个校园问题</span>
            <svg class="proof-route" viewBox="0 0 120 38" aria-hidden="true"><path d="M2 19H48Q58 19 65 10T84 19H117" /><circle cx="85" cy="19" r="3" /></svg>
            <span class="proof-source"><span class="source-sheets" aria-hidden="true"><i></i><i></i><i></i></span> 有据可循的回答</span>
          </div>
          <div class="hero-footnote"><span>江西师范大学 · 校园知识与智能交互</span><a href="#conversation" aria-label="向下浏览产品介绍"><span>继续探索</span><Icon name="chevronDown" :size="15" /></a></div>
        </div>

        <div id="access" ref="formArea" class="access-space" :aria-busy="submitting">
          <template v-if="auth.user">
            <p class="access-context">欢迎回来，{{ auth.user.username }}</p>
            <h2>接着上一问，<br />也可以重新开始。</h2>
            <p class="access-description">你的会话与记忆，留在自己的空间。</p>
            <RouterLink to="/inquiry" class="entry-submit">进入问学 <Icon name="arrowRight" :size="18" /></RouterLink>
            <button class="text-action" type="button" @click="leaveAccount">退出当前账号</button><p v-if="error" role="alert" class="access-feedback">{{ error }}</p>
          </template>
          <template v-else>
            <div class="access-tabs" role="group" aria-label="选择登录或注册" :data-register="registering">
              <button type="button" :aria-pressed="!registering" :disabled="submitting" @click="switchMode('login')">登录</button>
              <button type="button" :aria-pressed="registering" :disabled="submitting" @click="switchMode('register')">注册</button>
              <span class="access-indicator" aria-hidden="true"></span>
            </div>
            <div class="access-stage" :class="{ 'is-register': registering }">
              <Transition name="access" mode="out-in" @before-leave="element => element.inert = true" @after-enter="nextTick(() => nameInput?.focus({ preventScroll: true }))">
                <form :key="registering ? 'register' : 'login'" class="access-form" @submit.prevent="submit">
                  <h2>{{ registering ? '给好奇心，一个起点。' : '你好，今天想问什么？' }}</h2>
                  <p class="access-description">{{ registering ? '创建账号，开始自己的校园问学。' : route.query.changed ? '密码已更新，请使用新密码登录。' : '登录饭饭，继续你的校园探索。' }}</p>
                  <div class="access-fields">
                    <label class="entry-field"><span>用户名</span><input ref="nameInput" v-model="username" name="username" autocomplete="username" placeholder="你的用户名" minlength="3" maxlength="32" required :disabled="submitting" :aria-invalid="invalidField === 'username'" aria-describedby="access-feedback" /></label>
                    <label class="entry-field"><span>密码</span><span class="password-control"><input ref="passwordInput" v-model="password" name="password" :aria-invalid="invalidField === 'password'" :type="showPassword ? 'text' : 'password'" :autocomplete="registering ? 'new-password' : 'current-password'" placeholder="至少 8 个字符" minlength="8" maxlength="128" required :disabled="submitting" aria-describedby="access-feedback" /><button type="button" :aria-label="showPassword ? '隐藏密码' : '显示密码'" :aria-pressed="showPassword" @click="showPassword = !showPassword">{{ showPassword ? '隐藏' : '显示' }}</button></span></label>
                    <label v-if="registering" class="entry-field"><span>确认密码</span><input ref="confirmationInput" v-model="confirmation" name="confirm-password" :aria-invalid="invalidField === 'confirmation'" :type="showPassword ? 'text' : 'password'" autocomplete="new-password" placeholder="再次输入密码" minlength="8" maxlength="128" required :disabled="submitting" aria-describedby="access-feedback" /></label>
                  </div>
                  <p id="access-feedback" class="access-feedback" role="alert">{{ fieldError || error }}</p>
                  <button class="entry-submit" type="submit" :disabled="submitting"><span>{{ submitting ? '正在连接…' : registering ? '创建账号，开始问学' : '登录，进入问学' }}</span><Icon v-if="!submitting" name="arrowRight" :size="18" /><span v-else class="submit-loader" aria-hidden="true"></span></button>
                  <p class="access-note">{{ registering ? '用户名使用字母、数字、下划线或连字符。' : '会话与个人记忆，仅在你的账号下管理。' }}</p>
                </form>
              </Transition>
            </div>
            <p v-if="networkError" class="service-note" role="status">{{ networkError }} <button type="button" @click="retryIdentity">重试连接</button></p>
          </template>
        </div>
      </section>

      <section id="conversation" class="conversation-chapter chapter" data-depth aria-labelledby="conversation-title">
        <div class="chapter-heading" data-reveal><h2 id="conversation-title">问题很日常。<br /><span>回答，可以更有来路。</span></h2><p>从校园资料中寻找线索，用自然语言继续追问。<br />深度思考、工具轨迹与多轮对话，都在问学里。</p></div>
        <div class="conversation-scene" data-reveal>
          <div class="question-selector" role="group" aria-label="选择演示问题"><span class="demo-label">交互示例 · 非实时回答</span><button v-for="(item, index) in examples" :key="item.question" type="button" :aria-pressed="example === index" @click="example = index; sourceOpen = false"><span>{{ item.question }}</span><Icon name="arrowRight" :size="17" /></button></div>
          <div class="answer-preview" aria-live="polite"><span class="preview-product">饭饭 <span>问学</span></span><Transition name="example" mode="out-in"><div :key="example"><p class="preview-question">{{ current.question }}</p><p class="thinking-line"><Icon name="sparkle" :size="14" /> 查询可访问的文档，再组织回答</p><p class="preview-answer">{{ current.answer }} <button type="button" class="citation-mark" aria-label="查看示例引用" :aria-expanded="sourceOpen" @click="sourceOpen = !sourceOpen">[1]</button></p><div v-if="sourceOpen" class="inline-source"><strong>产品功能说明（示例文档）</strong><p>{{ current.excerpt }}</p></div></div></Transition><span class="preview-rule"></span><p class="preview-caption">对话不止于一句回答，也可以沿着线索继续。</p></div>
        </div>
      </section>

      <section id="evidence" class="evidence-chapter chapter" data-depth aria-labelledby="evidence-title">
        <div class="evidence-copy" data-reveal><h2 id="evidence-title">答案之外，<br />还有<span>依据。</span></h2><p>不必停在“它说了什么”。<br />打开引用，看看“它从哪里来”。</p><button type="button" class="evidence-toggle" :aria-expanded="sourceOpen" @click="sourceOpen = !sourceOpen">{{ sourceOpen ? '收起原文片段' : '展开一处引用' }} <Icon name="arrowRight" :size="19" /></button><p class="evidence-note">文档名、章节与原文片段<br />让知识的来路清晰可见。</p></div>
        <div class="document-composition" data-reveal><div class="document-leaf"><div class="document-top"><Icon name="archive" :size="18" /><span>产品功能说明</span><span>示例</span></div><h3>从回答，回到原文。</h3><div class="document-lines" aria-hidden="true"><i></i><i></i><i></i></div><p class="document-highlight" :class="{ 'is-open': sourceOpen }">{{ current.excerpt }}</p><div class="document-lines short" aria-hidden="true"><i></i><i></i></div><div class="document-bottom"><span>引用溯源演示</span><span>原文片段</span></div></div><div class="source-slip" :class="{ 'is-open': sourceOpen }"><span class="slip-index">[1]</span><div><strong>每一处引用，都是一条回路。</strong><p>{{ sourceOpen ? '已定位到对应片段，可继续阅读上下文。' : '点击左侧按钮，查看引用与原文的对应关系。' }}</p></div></div></div>
      </section>

      <section id="constellation" class="constellation-chapter" data-depth aria-labelledby="constellation-title">
        <div class="constellation-inner"><div class="constellation-heading" data-reveal><h2 id="constellation-title">把知识展开，<br />看见新的联系。</h2><p>从一份文档，到一颗颗知识星体。<br />在星野中浏览分片、定位内容、探索关联。</p><span class="graph-demo-label">知识星图示意 · 可选择节点</span></div><div class="constellation-preview" data-reveal><svg viewBox="0 0 760 490" role="group" aria-label="可交互的知识星图示意"><ellipse class="graph-orbit" cx="385" cy="250" rx="270" ry="137" transform="rotate(-19 385 250)" /><ellipse class="graph-orbit second" cx="385" cy="250" rx="215" ry="180" transform="rotate(28 385 250)" /><g class="graph-satellites"><circle v-for="(point,index) in satellites" :key="index" :cx="point.x" :cy="point.y" :r="point.r" /></g><g class="graph-links"><path d="M372 202L469 291L278 310L372 202L540 169L469 291" /><path d="M278 310L540 169" class="semantic-link" /></g><g v-for="(node,index) in nodes" :key="node.title" role="button" tabindex="0" :aria-label="`查看${node.title}示例`" :aria-pressed="selectedNode === index" class="graph-node" :class="{ selected: selectedNode === index }" @click="selectedNode=index" @keydown.enter.prevent="selectedNode=index" @keydown.space.prevent="selectedNode=index"><circle :cx="node.x" :cy="node.y" r="22" class="node-target" /><circle :cx="node.x" :cy="node.y" r="6" class="node-core" /><circle :cx="node.x" :cy="node.y" r="14" class="node-ring" /><text :x="node.x+23" :y="node.y+5">{{ node.title }}</text></g></svg><div class="graph-node-controls" role="group" aria-label="选择星图示例节点"><button v-for="(node,index) in nodes" :key="node.title" type="button" :aria-pressed="selectedNode === index" @click="selectedNode=index">{{ node.title }}</button></div><div class="graph-selection" aria-live="polite"><strong>{{ nodes[selectedNode].title }}</strong><span>{{ nodes[selectedNode].text }}</span></div></div></div>
        <div class="constellation-bottom"><span>星链记录文档顺序 · 语义连线呈现内容关联</span><span>从问学出发，在星野相遇。</span></div>
      </section>

      <section class="entry-closing chapter" data-reveal><span class="closing-word" aria-hidden="true">问</span><div><h2>下一问，<br />从你开始。</h2><p>把日常的好奇，带进自己的校园知识空间。</p><RouterLink v-if="auth.user" to="/inquiry" class="closing-action">进入问学 <Icon name="arrowRight" :size="22" /></RouterLink><button v-else type="button" class="closing-action" @click="focusForm">{{ registering ? '创建你的账号' : '登录饭饭' }} <Icon name="arrowRight" :size="22" /></button></div></section>
    </main>
    <footer class="entry-footer"><span>饭饭 <span>校园智能体</span></span><span>问学 · 典藏 · 记忆 · 星野</span><a href="#entry-start">回到开始 <Icon name="chevronUp" :size="14" /></a></footer>
  </div>
</template>

<style scoped>
/* ─────────────────────────────────────────────────────────────
   入口：一层纸，一扇门。
   样式按"外壳 → 首屏 → 表单 → 章节 → 动效"顺序书写，
   不再用层层覆盖的方式打补丁。
   ───────────────────────────────────────────────────────────── */
.entrance {
  --paper: #fbfbf9;
  --sheet: #ffffff;
  --text: #1e1e1c;
  --muted: #6a6a64;
  --line: rgba(30, 30, 28, 0.1);
  --rule: rgba(30, 30, 28, 0.28);
  --accent: #262624;
  --accent-hover: #111110;
  --on-accent: #ffffff;
  --wash: #f4f3ef;
  --night: #151716;
  --night-text: #f1f1ed;
  --night-muted: #b9bcb6;
  --star: #dcb489;
  --r-card: 22px;
  --r-panel: 14px;
  --r-field: 10px;
  --shadow-card: 0 1px 2px rgba(28, 24, 18, 0.04);
  --shadow-lift: 0 28px 60px -46px rgba(28, 24, 18, 0.55);

  background: var(--paper);
  color: var(--text);
  font-size: 16px;
  line-height: 1.75;
  overflow: clip;
}

.entrance :is(button, a, input) { -webkit-tap-highlight-color: transparent; }
.entrance :is(button, a, input):focus-visible { outline: 2px solid var(--accent); outline-offset: 4px; }
.entrance ::selection { background: #e6e4dd; color: var(--text); }
.entrance a { text-decoration: none; }

.entry-header,
.entry-hero,
.chapter,
.constellation-inner,
.constellation-bottom,
.entry-footer {
  width: min(100% - 112px, 1328px);
  margin-inline: auto;
}

/* ---------------------------------------------------------- 页头 */
.entry-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 24px;
  min-height: 92px;
  border-bottom: 1px solid var(--line);
  animation: entry-descend 720ms var(--ease-out) both;
}
.entry-brand { display: flex; align-items: center; gap: 12px; flex: none; }
.entry-brand-seal { width: 48px; height: 48px; }
.entry-brand-wordmark { width: 168px; height: auto; }
.entry-header nav { display: flex; gap: 34px; font-size: 14px; }
.entry-header nav a { position: relative; color: var(--muted); transition: color 220ms var(--ease-out); }
.entry-header nav a::after { content: ""; position: absolute; left: 0; right: 0; bottom: -6px; height: 1px; background: currentColor; transform: scaleX(0); transform-origin: left; transition: transform 280ms var(--ease-out); }
.entry-header nav a:hover { color: var(--text); }
.entry-header nav a:hover::after { transform: scaleX(1); }
.header-action { display: inline-flex; align-items: center; gap: 16px; padding: 7px 0; font-size: 14px; border-bottom: 1px solid var(--rule); transition: color 220ms var(--ease-out), border-color 220ms var(--ease-out); }
.header-action svg { transition: transform 320ms var(--ease-out); }
.header-action:hover { color: var(--accent-hover); border-color: var(--accent); }
.header-action:hover svg { transform: translateX(5px); }

/* ---------------------------------------------------------- 首屏 */
.entry-hero {
  display: grid;
  grid-template-columns: minmax(0, 1.12fr) minmax(360px, 0.88fr);
  align-items: stretch;
  gap: clamp(24px, 4vw, 56px);
  min-height: calc(100svh - 92px);
  padding-block: 28px 40px;
}

.hero-story {
  position: relative;
  display: flex;
  flex-direction: column;
  justify-content: center;
  min-height: 560px;
  padding: clamp(40px, 5vw, 76px);
  border-radius: var(--r-card);
  background: var(--wash);
  overflow: hidden;
  isolation: isolate;
}
.hero-story > :not(.hero-glyph) { position: relative; z-index: 1; }
.hero-footnote { margin-top: auto; padding-top: 40px; }
.hero-glyph {
  position: absolute;
  right: -0.06em;
  bottom: -0.3em;
  z-index: 0;
  font-family: var(--font-serif);
  font-size: clamp(280px, 36vw, 560px);
  line-height: 1;
  color: rgba(30, 30, 28, 0.034);
  user-select: none;
  transform: rotate(-7deg);
  animation: glyph-arrive 1400ms 160ms var(--ease-out) both;
}

.hero-edition { display: flex; justify-content: space-between; gap: 20px; max-width: 640px; margin-bottom: clamp(34px, 6vh, 64px); padding-bottom: 16px; border-bottom: 1px solid #dedcd4; color: var(--muted); font-size: 12px; letter-spacing: 0.06em; }
.hero-story h1 { font-family: var(--font-serif); font-size: clamp(42px, 4.6vw, 70px); font-weight: 500; line-height: 1.34; letter-spacing: -0.035em; color: var(--text); text-wrap: balance; }
.title-orbit { position: relative; color: var(--accent); white-space: nowrap; }
.title-orbit svg { position: absolute; left: 0; bottom: -12px; width: 100%; height: 24px; fill: none; stroke: var(--accent); stroke-width: 1.3; stroke-dasharray: 380; animation: draw-line 1200ms 760ms var(--ease-out) both; }
.hero-description { margin-top: 28px; color: var(--muted); font-size: 16px; line-height: 1.95; }

.hero-proof { display: flex; align-items: center; gap: 17px; margin-block: 44px 30px; color: #52524c; font-size: 14px; }
.proof-ask, .proof-source { display: flex; align-items: center; gap: 10px; }
.proof-ask > svg { color: var(--accent); }
.proof-route { width: 100px; height: 38px; fill: none; stroke: #b9b7ae; stroke-width: 1; }
.proof-route circle { fill: var(--accent); stroke: none; }
.source-sheets { position: relative; width: 25px; height: 30px; }
.source-sheets i { position: absolute; inset: 4px 5px 3px 0; border: 1px solid #b9b7ae; background: var(--wash); transform: rotate(-11deg); }
.source-sheets i:nth-child(2) { transform: translateX(4px) rotate(5deg); }
.source-sheets i:last-child { transform: translateX(8px) rotate(14deg); border-color: var(--accent); }

.hero-footnote { display: flex; align-items: center; justify-content: space-between; gap: 16px; margin-top: auto; padding-top: 22px; border-top: 1px solid #dedcd4; color: var(--muted); font-size: 12px; }
.hero-footnote a { display: flex; align-items: center; gap: 10px; transition: color 220ms var(--ease-out); }
.hero-footnote a svg { transition: transform 320ms var(--ease-out); }
.hero-footnote a:hover { color: var(--text); }
.hero-footnote a:hover svg { transform: translateY(3px); }

/* ---------------------------------------------------------- 表单 */
.access-space {
  display: flex;
  flex-direction: column;
  justify-content: center;
  padding: clamp(20px, 3vw, 44px) 0 clamp(20px, 3vw, 44px) clamp(28px, 3.4vw, 52px);
  border-left: 1px solid var(--line);
  scroll-margin: 40px;
}
.access-tabs { position: relative; display: flex; width: 156px; margin-bottom: 30px; border-bottom: 1px solid var(--line); }
.access-tabs button { width: 78px; padding: 9px 0 13px; color: var(--muted); font-size: 15px; transition: color 220ms var(--ease-out); }
.access-tabs button[aria-pressed="true"] { color: var(--text); }
.access-indicator { position: absolute; left: 0; bottom: -1px; width: 50%; height: 1.5px; background: var(--accent); transition: transform 420ms var(--ease-out); }
.access-tabs[data-register="true"] .access-indicator { transform: translate3d(100%, 0, 0); }

.access-space h2 { font-family: var(--font-serif); font-size: clamp(23px, 2vw, 29px); font-weight: 500; line-height: 1.5; letter-spacing: -0.015em; }
.access-description { margin-top: 8px; color: var(--muted); font-size: 14px; }
.access-context { margin-bottom: 24px; color: var(--muted); font-size: 14px; }
.access-stage { min-height: 372px; transition: min-height 420ms var(--ease-out); }
.access-stage.is-register { min-height: 462px; }
.access-fields { display: grid; gap: 20px; margin-top: 26px; }
.entry-field { display: grid; gap: 6px; font-size: 13px; }
.entry-field > span:first-child { color: var(--muted); transition: color 200ms var(--ease-out); }
.entry-field:focus-within > span:first-child { color: var(--text); }
.entry-field input {
  width: 100%;
  min-width: 0;
  min-height: 46px;
  padding: 11px 14px;
  border: 1px solid #dddbd3;
  border-radius: var(--r-field);
  background: #fbfbf9;
  font-size: 15px;
  color: var(--text);
  transition: border-color 200ms var(--ease-out), background 200ms var(--ease-out), box-shadow 200ms var(--ease-out);
}
.entry-field input::placeholder { color: #8a8a83; font-size: 14px; }
.entry-field input:hover { border-color: #c9c7be; }
.entry-field input:focus { outline: none; border-color: var(--accent); background: #fff; box-shadow: 0 0 0 3px rgba(38, 38, 36, 0.1); }
.entry-field input[aria-invalid="true"] { border-color: #a4483d; }
.password-control { position: relative; display: flex; }
.password-control input { padding-right: 56px; }
.password-control button { position: absolute; right: 10px; bottom: 11px; padding: 4px 6px; color: var(--muted); font-size: 12px; border-radius: 6px; transition: color 200ms var(--ease-out), background 200ms var(--ease-out); }
.password-control button:hover { color: var(--text); background: #f0efea; }

.access-feedback { min-height: 22px; margin: 9px 0 4px; color: #a4483d; font-size: 12.5px; }
.entry-submit {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  width: 100%;
  min-height: 50px;
  padding: 12px 18px;
  border-radius: var(--r-field);
  background: var(--accent);
  color: var(--on-accent);
  font-size: 15px;
  transition: background 220ms var(--ease-out), transform 220ms var(--ease-out), box-shadow 220ms var(--ease-out);
}
.entry-submit svg { transition: transform 320ms var(--ease-out); }
.entry-submit:hover:not(:disabled) { background: var(--accent-hover); transform: translateY(-1px); box-shadow: 0 12px 26px -18px rgba(28, 24, 18, 0.7); }
.entry-submit:hover:not(:disabled) svg { transform: translateX(5px); }
.entry-submit:active:not(:disabled) { transform: translateY(0); box-shadow: none; }
.entry-submit:disabled { cursor: wait; opacity: 0.72; }
.access-note { margin-top: 14px; color: var(--muted); font-size: 12px; }
.service-note { margin-top: 14px; color: var(--muted); font-size: 12px; }
.service-note button { margin-left: 6px; color: var(--text); border-bottom: 1px solid var(--rule); }
.submit-loader { width: 15px; height: 15px; border: 1.5px solid rgba(255, 255, 255, 0.35); border-top-color: #fff; border-radius: 50%; animation: spin 700ms linear infinite; }
.text-action { margin-top: 14px; color: var(--muted); font-size: 13px; border-bottom: 1px solid var(--line); transition: color 200ms var(--ease-out); }
.text-action:hover { color: var(--text); }
.skip-entry { position: fixed; left: 20px; top: 15px; z-index: 99; padding: 10px 20px; background: var(--paper); border: 1px solid var(--accent); transform: translateY(-160%); transition: transform 200ms var(--ease-out); }
.skip-entry:focus { transform: none; }

/* ---------------------------------------------------------- 章节公共 */
.chapter { padding-block: clamp(80px, 9vw, 138px); }
.conversation-chapter { border-top: 1px solid var(--line); }
.chapter-heading { display: flex; align-items: flex-end; justify-content: space-between; gap: 40px; margin-bottom: 56px; }
.chapter h2, .constellation-heading h2, .evidence-copy h2 { font-family: var(--font-serif); font-size: clamp(36px, 4vw, 58px); font-weight: 500; line-height: 1.36; letter-spacing: -0.028em; }
.chapter-heading h2 > span { color: var(--muted); }
.chapter-heading > p { max-width: 30ch; text-wrap: pretty; padding-bottom: 8px; color: var(--muted); font-size: 14px; line-height: 1.9; }

/* 问有所答 */
.conversation-scene { display: grid; grid-template-columns: minmax(260px, 0.82fr) minmax(0, 1.18fr); gap: clamp(36px, 6vw, 92px); }
.question-selector { display: flex; flex-direction: column; }
.demo-label { margin-bottom: 18px; color: var(--muted); font-size: 12px; letter-spacing: 0.04em; }
.question-selector button {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 22px;
  padding: 21px 0;
  border-top: 1px solid var(--line);
  color: var(--muted);
  font-size: 15.5px;
  text-align: left;
  transition: color 240ms var(--ease-out), padding 320ms var(--ease-out);
}
.question-selector button:last-of-type { border-bottom: 1px solid var(--line); }
.question-selector button svg { flex-shrink: 0; opacity: 0.3; transition: opacity 240ms var(--ease-out), transform 320ms var(--ease-out); }
.question-selector button:hover { color: var(--text); padding-left: 6px; }
.question-selector button[aria-pressed="true"] { color: var(--text); padding-left: 12px; }
.question-selector button[aria-pressed="true"] svg { opacity: 1; transform: translateX(2px); }

.answer-preview { display: flex; flex-direction: column; min-height: 372px; padding: 32px 34px 26px; border: 1px solid #ebe9e2; border-radius: var(--r-panel); background: #f7f7f4; }
.preview-product { font-family: var(--font-serif); font-size: 22px; }
.preview-product > span { margin-left: 12px; color: var(--muted); font-family: var(--font-ui); font-size: 12px; }
.preview-question { margin-top: 22px; font-family: var(--font-serif); font-size: 18px; }
.thinking-line { display: flex; align-items: center; gap: 8px; margin-block: 16px 10px; color: var(--muted); font-size: 12px; }
.preview-answer { font-size: 15.5px; line-height: 1.95; }
.citation-mark { padding: 0 4px; color: var(--accent); font-size: 12px; vertical-align: super; border-radius: 4px; transition: background 200ms var(--ease-out); }
.citation-mark:hover { background: #e6e4dd; }
.inline-source { margin-top: 12px; padding-top: 12px; border-top: 1px solid var(--line); font-size: 13px; animation: source-open 320ms var(--ease-out) both; }
.inline-source p { margin-top: 5px; color: var(--muted); }
.preview-rule { display: block; width: 28px; margin-top: auto; padding-top: 26px; border-top: 1px solid var(--accent); }
.preview-caption { margin-top: 12px; color: var(--muted); font-size: 12px; }

/* 答有所据 */
.evidence-chapter { display: grid; grid-template-columns: minmax(0, 0.72fr) minmax(0, 1.28fr); align-items: center; gap: clamp(40px, 7vw, 96px); padding-block: clamp(70px, 8vw, 120px); }
.evidence-copy > p { margin-top: 22px; color: var(--muted); line-height: 1.9; }
.evidence-toggle { display: flex; align-items: center; gap: 26px; margin-top: 32px; padding-bottom: 10px; color: var(--text); font-size: 15px; border-bottom: 1px solid var(--rule); transition: gap 320ms var(--ease-out), border-color 220ms var(--ease-out); }
.evidence-toggle svg { transition: transform 320ms var(--ease-out); }
.evidence-toggle:hover { gap: 34px; border-color: var(--accent); }
.evidence-toggle:hover svg { transform: translateX(3px); }
.evidence-note { margin-top: 20px; color: var(--muted); font-size: 13px !important; line-height: 1.75; }

.document-composition { position: relative; padding: 24px 40px 44px 16px; }
.document-leaf { position: relative; padding: 30px 34px 22px; border-radius: var(--r-panel); background: var(--sheet); box-shadow: var(--shadow-lift); transform: rotate(-2.4deg); transition: transform 640ms var(--ease-out); }
.document-composition:hover .document-leaf { transform: rotate(-1deg); }
.document-top { display: flex; align-items: center; gap: 10px; padding-bottom: 18px; border-bottom: 1px solid var(--line); color: var(--muted); font-size: 12px; }
.document-top > span:last-child { margin-left: auto; }
.document-leaf h3 { margin-block: 22px; font-family: var(--font-serif); font-size: 25px; font-weight: 500; }
.document-lines { display: grid; gap: 11px; margin-block: 22px; }
.document-lines i { height: 1px; background: #e6e3da; }
.document-lines i:last-child { width: 70%; }
.document-highlight { padding: 9px 0; font-size: 15px; line-height: 1.95; transition: background 360ms var(--ease-out), box-shadow 360ms var(--ease-out); }
.document-highlight.is-open { background: #efedE6; box-shadow: 10px 0 0 #efedE6, -10px 0 0 #efedE6; }
.document-bottom { display: flex; justify-content: space-between; padding-top: 16px; border-top: 1px solid var(--line); color: var(--muted); font-size: 12px; }

.source-slip { position: relative; display: flex; gap: 16px; margin: -6px -16px 0 44px; padding: 19px 22px; border: 1px solid #ddd9cf; border-radius: 12px; background: var(--paper); transform: rotate(1.6deg); transition: transform 420ms var(--ease-out), border-color 300ms var(--ease-out), box-shadow 420ms var(--ease-out); }
.source-slip.is-open { transform: rotate(0deg) translateY(8px); border-color: var(--accent); box-shadow: 0 18px 40px -34px rgba(28, 24, 18, 0.6); }
.slip-index { color: var(--accent); font-family: var(--font-mono); font-size: 13px; }
.source-slip strong { font-size: 14px; font-weight: 500; }
.source-slip p { margin-top: 4px; color: var(--muted); font-size: 12.5px; }

/* 知识成图 */
.constellation-chapter { padding: 100px 0 30px; background: var(--night); color: var(--night-text); }
.constellation-inner { display: grid; grid-template-columns: minmax(0, 0.78fr) minmax(0, 1.22fr); align-items: center; gap: 18px; }
.constellation-heading { position: relative; z-index: 1; }
.constellation-heading > p { margin-top: 24px; color: var(--night-muted); font-size: 14px; line-height: 1.9; }
.graph-demo-label { display: block; margin-top: 34px; color: var(--night-muted); font-size: 12px; }
.constellation-preview { min-width: 0; }
.constellation-preview > svg { width: 112%; max-width: none; margin-left: -7%; overflow: visible; }
.graph-orbit { fill: none; stroke: rgba(214, 218, 210, 0.16); stroke-width: 0.7; }
.graph-orbit.second { stroke-dasharray: 3 8; }
.graph-satellites { fill: var(--night-muted); opacity: 0.55; transform-origin: 385px 250px; animation: constellation-breathe 40s ease-in-out infinite alternate; animation-play-state: paused; }
.entrance:not(.is-paused) .constellation-preview.is-visible .graph-satellites { animation-play-state: running; }
.graph-links { fill: none; stroke: #8d918a; stroke-width: 0.8; }
.semantic-link { stroke-dasharray: 4 5; opacity: 0.55; }
.graph-node { cursor: pointer; outline: none; }
.node-target { fill: transparent; }
.node-core { fill: var(--night-text); transition: fill 300ms var(--ease-out), r 300ms var(--ease-out); }
.node-ring { fill: none; stroke: var(--night-muted); stroke-width: 0.6; opacity: 0; transition: opacity 300ms var(--ease-out); }
.graph-node text { fill: var(--night-muted); font-size: 14px; transition: fill 300ms var(--ease-out); }
.graph-node:hover .node-core { fill: var(--star); }
.graph-node.selected .node-core { fill: var(--star); r: 8; }
.graph-node.selected .node-ring, .graph-node:focus-visible .node-ring { opacity: 1; stroke: var(--star); }
.graph-node.selected text { fill: var(--night-text); }
.graph-node-controls { display: none; }
.graph-selection { display: flex; align-items: center; gap: 22px; min-height: 68px; padding: 16px 0; border-top: 1px solid rgba(214, 218, 210, 0.16); font-size: 14px; }
.graph-selection strong { font-family: var(--font-serif); font-size: 18px; font-weight: 400; color: var(--star); }
.graph-selection span { color: var(--night-muted); }
.constellation-bottom { display: flex; justify-content: space-between; gap: 20px; margin-top: 60px; padding-top: 22px; border-top: 1px solid rgba(214, 218, 210, 0.16); color: var(--night-muted); font-size: 12px; }

/* 收束 */
.entry-closing { display: grid; grid-template-columns: 1fr 1fr; align-items: center; gap: 80px; padding-block: clamp(90px, 10vw, 130px); border-bottom: 1px solid var(--line); }
.closing-word { font-family: var(--font-serif); font-size: clamp(160px, 21vw, 300px); line-height: 1; color: var(--accent); text-align: center; opacity: 0.9; }
.entry-closing p { margin-top: 18px; color: var(--muted); font-size: 15px; }
.closing-action { display: inline-flex; align-items: center; gap: 42px; margin-top: 26px; padding: 11px 0; color: var(--text); font-size: 17px; border-bottom: 1px solid var(--rule); transition: gap 340ms var(--ease-out), border-color 220ms var(--ease-out); }
.closing-action:hover { gap: 50px; border-color: var(--accent); }
.entry-footer { display: flex; align-items: center; justify-content: space-between; gap: 22px; padding-block: 26px 32px; color: var(--muted); font-size: 12px; }
.entry-footer > span:first-child { color: var(--text); font-family: var(--font-serif); font-size: 21px; }
.entry-footer > span:first-child span { margin-left: 9px; font-family: var(--font-ui); font-size: 12px; }
.entry-footer a { display: flex; align-items: center; gap: 8px; }
.entry-footer a svg { transition: transform 320ms var(--ease-out); }
.entry-footer a:hover svg { transform: translateY(-3px); }

/* ---------------------------------------------------------- 动效 */
/* 首屏：自上而下的分层入场 */
.hero-edition, .hero-story h1, .hero-description, .hero-proof, .hero-footnote,
.access-tabs, .access-form > h2, .access-form > .access-description,
.access-form > .access-fields, .access-form > .access-feedback,
.access-form > .entry-submit, .access-form > .access-note {
  animation: entry-descend 760ms var(--ease-out) both;
}
.hero-edition { animation-delay: 40ms; }
.hero-story h1 { animation-delay: 110ms; }
.hero-description { animation-delay: 190ms; }
.hero-proof { animation-delay: 270ms; }
.hero-footnote { animation-delay: 350ms; }
.access-tabs { animation-delay: 150ms; }
.access-form > .access-description { animation-delay: 260ms; }
.access-form > .access-fields { animation-delay: 330ms; }
.access-form > .access-feedback { animation-delay: 390ms; }
.access-form > .entry-submit { animation-delay: 440ms; }
.access-form > .access-note { animation-delay: 500ms; }
.entrance:not(.has-switched-mode) .access-form > h2 { animation-delay: 210ms; }

@keyframes entry-descend {
  from { opacity: 0; filter: blur(7px); transform: translateY(-14px); }
  60% { opacity: 1; }
  to { opacity: 1; filter: blur(0); transform: none; }
}
@keyframes glyph-arrive {
  from { opacity: 0; transform: translate3d(4%, 4%, 0) rotate(-3deg); }
  to { opacity: 1; transform: rotate(-7deg); }
}
@keyframes draw-line { from { stroke-dashoffset: 380; } to { stroke-dashoffset: 0; } }
@keyframes spin { to { transform: rotate(360deg); } }
@keyframes source-open { from { opacity: 0; transform: translateY(-4px); } to { opacity: 1; transform: none; } }

/* 滚动章节：每章一套入场，互不重复 */
[data-reveal] { opacity: 1; }
[data-reveal].is-seen { animation: reveal-rise 820ms var(--ease-out) both; }

@keyframes reveal-rise {
  from { opacity: 0; filter: blur(6px); transform: translateY(26px); }
  to { opacity: 1; filter: blur(0); transform: none; }
}

/* 问有所答：标题自左，示例自右侧依次升起，答案卡轻微下沉 */
#conversation .chapter-heading { animation-name: reveal-left; }
.question-selector button { animation: reveal-rise 620ms var(--ease-out) both; }
.question-selector button:nth-of-type(1) { animation-delay: 90ms; }
.question-selector button:nth-of-type(2) { animation-delay: 160ms; }
.question-selector button:nth-of-type(3) { animation-delay: 230ms; }
.answer-preview { animation: reveal-card 780ms 140ms var(--ease-out) both; }

@keyframes reveal-left {
  from { opacity: 0; filter: blur(5px); transform: translateX(-22px); }
  to { opacity: 1; filter: blur(0); transform: none; }
}
@keyframes reveal-card {
  from { opacity: 0; filter: blur(8px); transform: translateY(30px) scale(0.985); }
  to { opacity: 1; filter: blur(0); transform: none; }
}

/* 答有所据：文案先到，纸页随后翻上，引条最后滑入 */
#evidence .evidence-copy { animation-name: reveal-left; }
.document-composition { animation: leaf-arrive 900ms 120ms var(--ease-out) both; }
@keyframes leaf-arrive {
  from { opacity: 0; filter: blur(8px); transform: translateY(34px) rotate(-3deg); }
  to { opacity: 1; filter: blur(0); transform: none; }
}
.source-slip { animation: slip-arrive 720ms 380ms var(--ease-out) both; }
@keyframes slip-arrive {
  from { opacity: 0; transform: translate(-18px, 14px) rotate(-2deg); }
  to { opacity: 1; transform: none; }
}

/* 知识成图：标题先亮，星点随后逐个亮起，轨道线最后描出 */
#constellation .constellation-heading { animation-name: reveal-rise; }
.constellation-preview { animation: graph-arrive 980ms 160ms var(--ease-out) both; }
@keyframes graph-arrive {
  from { opacity: 0; filter: blur(10px); transform: scale(0.97); }
  to { opacity: 1; filter: blur(0); transform: none; }
}
.graph-orbit { stroke-dasharray: 1200; stroke-dashoffset: 1200; }
.constellation-preview.is-visible .graph-orbit { animation: orbit-draw 1600ms 320ms var(--ease-out) forwards; }
.constellation-preview.is-visible .graph-links path { stroke-dasharray: 420; stroke-dashoffset: 420; animation: orbit-draw 1400ms 620ms var(--ease-out) forwards; }
@keyframes orbit-draw { to { stroke-dashoffset: 0; } }
.graph-node { opacity: 0; }
.constellation-preview.is-visible .graph-node { animation: node-pop 620ms var(--ease-out) forwards; }
.constellation-preview.is-visible .graph-node:nth-of-type(1) { animation-delay: 180ms; }
.constellation-preview.is-visible .graph-node:nth-of-type(2) { animation-delay: 260ms; }
.constellation-preview.is-visible .graph-node:nth-of-type(3) { animation-delay: 340ms; }
.constellation-preview.is-visible .graph-node:nth-of-type(4) { animation-delay: 420ms; }
@keyframes node-pop {
  from { opacity: 0; }
  to { opacity: 1; }
}

/* 收束：字先立住，文案随后 */
.entry-closing .closing-word { animation: closing-word 900ms var(--ease-out) both; }
@keyframes closing-word {
  from { opacity: 0; filter: blur(10px); transform: scale(0.94); }
  to { opacity: 0.9; filter: blur(0); transform: none; }
}

/* 表单切换与示例切换 */
.access-enter-active, .access-leave-active { transition: opacity 220ms var(--ease-out), transform 300ms var(--ease-out), filter 300ms var(--ease-out); }
.access-enter-from { opacity: 0; filter: blur(4px); transform: translate3d(14px, 6px, 0); }
.access-leave-to { opacity: 0; filter: blur(4px); transform: translate3d(-12px, -4px, 0); }
.access-leave-active { pointer-events: none; }
.example-enter-active, .example-leave-active { transition: opacity 200ms var(--ease-out), transform 260ms var(--ease-out); }
.example-enter-from { opacity: 0; transform: translateY(8px); }
.example-leave-to { opacity: 0; transform: translateY(-6px); }

/* ---------------------------------------------------------- 响应式 */
@media (min-width: 1500px) {
  .entry-hero { padding-block: 40px 52px; }
}

@media (max-width: 1100px) {
  .entry-header, .entry-hero, .chapter, .entry-footer, .constellation-inner, .constellation-bottom { width: calc(100% - 64px); }
  .entry-hero { grid-template-columns: minmax(0, 1fr) minmax(330px, 0.9fr); gap: 28px; }
  .hero-story { min-height: 540px; padding: 42px; }
  .hero-story h1 { font-size: clamp(38px, 4.4vw, 52px); }
  .hero-proof { gap: 10px; font-size: 12px; }
  .proof-route { width: 62px; }
  .access-space { padding-left: 30px; }
  .evidence-chapter { gap: 40px; }
  .document-composition { padding-right: 14px; }
  .entry-header nav { gap: 20px; }
}

@media (max-width: 760px) {
  .entry-header, .entry-hero, .chapter, .entry-footer, .constellation-inner, .constellation-bottom { width: calc(100% - 40px); }
  .entry-header { min-height: 74px; gap: 14px; }
  .entry-brand { gap: 9px; }
  .entry-brand-seal { width: 40px; height: 40px; }
  .entry-brand-wordmark { width: clamp(110px, 36vw, 150px); }
  .entry-header nav { display: none; }
  .header-action { font-size: 13px; gap: 8px; }
  .entry-hero { display: flex; flex-direction: column; gap: 0; min-height: auto; width: calc(100% - 32px); padding-block: 8px 20px; }
  .hero-story { min-height: 220px; padding: 24px; border-radius: 18px; }
  .hero-edition { margin-bottom: 20px; padding-bottom: 12px; }
  .hero-story h1 { font-size: clamp(32px, 8.4vw, 46px); line-height: 1.32; }
  .hero-description { margin-top: 14px; font-size: 14px; }
  .hero-proof, .hero-footnote { display: none; }
  .hero-glyph { font-size: 62vw; bottom: -0.24em; }
  .access-space { padding: 24px 8px 26px; border-left: 0; border-top: 1px solid var(--line); }
  .access-stage { min-height: 372px; }
  .access-stage.is-register { min-height: 458px; }
  .access-fields { gap: 16px; margin-top: 22px; }
  .chapter { padding-block: 64px; }
  .chapter-heading { display: block; margin-bottom: 30px; }
  .chapter-heading > p { margin-top: 18px; font-size: 14px; }
  .chapter h2, .constellation-heading h2, .evidence-copy h2 { font-size: 32px; }
  .conversation-scene { grid-template-columns: 1fr; gap: 26px; }
  .question-selector button { padding-block: 16px; font-size: 14px; }
  .answer-preview { min-height: 340px; padding: 24px 22px; }
  .evidence-chapter { grid-template-columns: 1fr; gap: 30px; }
  .evidence-note { display: none; }
  .document-composition { padding: 14px 10px 18px 2px; }
  .document-leaf { padding: 22px; }
  .document-leaf h3 { font-size: 22px; }
  .source-slip { margin-left: 18px; margin-right: -4px; padding: 16px; }
  .constellation-chapter { padding-top: 64px; }
  .constellation-inner { grid-template-columns: 1fr; }
  .constellation-heading > p { font-size: 14px; }
  .graph-demo-label { margin-top: 20px; }
  .constellation-preview > svg { width: 118%; margin-left: -9%; }
  .constellation-bottom { flex-wrap: wrap; margin-top: 34px; }
  .graph-node-controls { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 8px; }
  .graph-node-controls button { padding: 6px 12px; border: 1px solid rgba(214, 218, 210, 0.22); border-radius: 999px; color: var(--night-muted); font-size: 12px; }
  .graph-node-controls button[aria-pressed="true"] { border-color: var(--star); color: var(--star); }
  .entry-closing { grid-template-columns: 1fr; gap: 30px; text-align: left; padding-block: 70px; }
  .closing-word { font-size: 44vw; line-height: 0.8; text-align: left; }
  .entry-footer { flex-wrap: wrap; gap: 12px; }
}

@media (prefers-reduced-motion: reduce) {
  .entrance *, .entrance *::before, .entrance *::after { animation: none !important; transition-duration: 120ms !important; scroll-behavior: auto !important; }
  .answer-preview, .document-composition, .constellation-preview { transform: none; }
}
</style>
