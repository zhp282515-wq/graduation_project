import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8002',
        changeOrigin: true,
      },
      // 上传的图片由后端静态托管
      '/uploads': {
        target: 'http://127.0.0.1:8002',
        changeOrigin: true,
      },
    },
  },
})
