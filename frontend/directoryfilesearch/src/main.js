import { createApp } from 'vue'
import { createVuetify } from 'vuetify'
import { aliases, mdi } from 'vuetify/iconsets/mdi'
import * as components from 'vuetify/components'
import * as directives from 'vuetify/directives'

import '@mdi/font/css/materialdesignicons.css'
import 'vuetify/styles'

import App from './App.vue'

const vuetify = createVuetify({
  components,
  directives,
  icons: {
    defaultSet: 'mdi',
    aliases,
    sets: { mdi },
  },
  theme: {
    defaultTheme: 'directorySearchLight',
    themes: {
      directorySearchLight: {
        dark: false,
        colors: {
          primary: '#2563eb',
          secondary: '#0f766e',
          success: '#15803d',
          warning: '#a16207',
          error: '#b91c1c',
          info: '#0369a1',
          background: '#f4f6f8',
          surface: '#ffffff',
        },
      },
    },
  },
})

createApp(App).use(vuetify).mount('#app')
