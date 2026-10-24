import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 后端仍然跑在 8002：接口路径、SSE、上传与 /uploads 静态目录都原样转发，
// 前端不改变任何契约，只换渲染。
const BACKEND = process.env.JXNU_API ?? 'http://127.0.0.1:8002'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  server: {
    host: '127.0.0.1',
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': { target: BACKEND, changeOrigin: true },
      '/uploads': { target: BACKEND, changeOrigin: true },
    },
  },
  preview: { host: '127.0.0.1', port: 4173 },
  build: {
    // three.js 只有星图用到，单独切一个长缓存 chunk，别让它拖慢问学首屏。
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes('node_modules/three')) return 'three'
          return undefined
        },
      },
    },
  },
  test: {
    environment: 'node',
    include: ['src/**/*.test.js', 'tests/**/*.test.js'],
  },
})
