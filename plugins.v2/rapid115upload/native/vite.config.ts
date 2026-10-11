import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import vueJsx from '@vitejs/plugin-vue-jsx'
import AutoImport from 'unplugin-auto-import/vite'
import Components from 'unplugin-vue-components/vite'
import VueI18n from '@intlify/unplugin-vue-i18n/vite'
import { resolve } from 'node:path'
export default defineConfig({
 base:'./',
 plugins:[vue(),vueJsx(),Components({dirs:['src/@core/components'],dts:false}),AutoImport({imports:['vue','vue-router','@vueuse/core','@vueuse/math','pinia','vue-i18n'],vueTemplate:true,dts:false}),VueI18n({include:[resolve('src/locales/*.ts')]})],
 resolve:{alias:[{find:/^@\/composables\/usePWA$/,replacement:resolve('pwa.ts')},{find:/^@\/api$/,replacement:resolve('runtime.ts')},{find:/^@\/router$/,replacement:resolve('router.ts')},{find:'@',replacement:resolve('src')},{find:'@images',replacement:resolve('src/assets/images')},{find:'@configured-variables',replacement:resolve('src/styles/variables/_template.scss')},{find:'@core',replacement:resolve('src/@core')},{find:'@styles',replacement:resolve('src/styles')},{find:'@layouts',replacement:resolve('src/@layouts')},{find:'@validators',replacement:resolve('src/@core/utils/validators')}]},
 define:{'process.env.NODE_ENV':JSON.stringify('production'),'__APP_VERSION__':JSON.stringify('v3.0.2'),'__BUILD_TIME__':JSON.stringify('plugin-native'),'__PWA_DEVELOPMENT__':'false','import.meta.env.VITE_API_BASE_URL':'window.__rapid115NativeBase'},
 build:{outDir:'../native-dist',emptyOutDir:true,lib:{entry:resolve('entry.ts'),formats:['es'],fileName:()=> 'native.js'},target:'esnext',cssCodeSplit:false},
})
