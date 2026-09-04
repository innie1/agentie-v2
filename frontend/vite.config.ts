import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { VitePWA } from 'vite-plugin-pwa'

export default defineConfig({
  root: 'web',
  plugins: [react(), VitePWA({
    registerType: 'autoUpdate',
    manifest: {
      name: 'Agentie', short_name: 'Agentie',
      description: 'Your local-first AI company workspace',
      theme_color: '#f6f7f9', background_color: '#f6f7f9',
      display: 'standalone', orientation: 'any', start_url: '/', scope: '/'
    },
    workbox: { navigateFallback: null, globPatterns: ['**/*.{js,css,html,ico,png,webmanifest}'] }
  })],
  build: { outDir: '../dist', emptyOutDir: true },
  server: { proxy: { '/agent': 'http://127.0.0.1:8000', '/plugins': 'http://127.0.0.1:8000' } }
})
