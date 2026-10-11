import { computed } from 'vue'
import { usePWA as useOriginalPWA } from './src/composables/usePWA'
export * from './src/composables/usePWA'
/** 插件内页没有宿主/history的底栏注册槽，使用原版独立页面FAB呈现全部操作。 */
export function usePWA() { return {...useOriginalPWA(),appMode:computed(()=>false)} }
