import { defineConfig } from 'vite';
import vue from '@vitejs/plugin-vue';

export default defineConfig({
  plugins: [vue()],
  publicDir: false,
  build: { outDir: '../app/web', emptyOutDir: false },
  server: { proxy: {
    '/api': { target: 'http://127.0.0.1:8765', changeOrigin: true, configure(proxy) { proxy.on('proxyReq', req => req.setHeader('Origin', 'http://127.0.0.1:8765')); } },
    '/vendor': 'http://127.0.0.1:8765',
  } },
});
