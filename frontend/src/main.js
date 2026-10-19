import { createApp } from 'vue'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import * as ElementPlusIconsVue from '@element-plus/icons-vue'
import App from './App.vue'
import { glassTilt } from './directives/glassTilt'
import { liquidButtons } from './directives/glassButtons'
import { applyPreset } from './glass/preset'

// 液态玻璃预设（myconfig）→ :root 上的 CSS 变量，整个界面共用一套
applyPreset()

const app = createApp(App)

for (const [key, component] of Object.entries(ElementPlusIconsVue)) {
  app.component(key, component)
}

app.directive('glass-tilt', glassTilt)
// 面板里的交互按钮交给液态玻璃层（面板本身是 CSS 玻璃）
app.directive('liquid-buttons', liquidButtons)
app.use(ElementPlus)
app.mount('#app')
