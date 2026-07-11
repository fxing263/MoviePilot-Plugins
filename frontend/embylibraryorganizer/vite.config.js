import { fileURLToPath, URL } from 'node:url'

import federation from '@originjs/vite-plugin-federation'
import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

export default defineConfig(({ command }) => ({
  plugins: [
    vue(),
    federation({
      name: 'embylibraryorganizer',
      filename: 'remoteEntry.js',
      exposes: {
        './Page': './src/components/Page.vue',
        './Config': './src/components/Config.vue',
      },
      shared: {
        vue: {
          requiredVersion: false,
          generate: false,
        },
        vuetify: {
          requiredVersion: false,
          generate: false,
          singleton: true,
        },
        'vuetify/styles': {
          requiredVersion: false,
          generate: false,
          singleton: true,
        },
      },
      format: 'esm',
    }),
  ],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  build: {
    target: 'esnext',
    cssCodeSplit: true,
    emptyOutDir: true,
    outDir: '../../plugins.v2/embylibraryorganizer/dist',
    rollupOptions: {
      input: command === 'build'
        ? fileURLToPath(new URL('./src/build.js', import.meta.url))
        : undefined,
    },
  },
  server: {
    port: 5002,
    cors: true,
    origin: 'http://localhost:5002',
  },
}))
