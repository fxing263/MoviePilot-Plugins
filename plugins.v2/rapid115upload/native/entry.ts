import { dynamicButtonRegistry } from './src/composables/dynamicButtonRegistry'
import { createApp } from 'vue'
import './src/@iconify/icons-bundle'
import Root from './Root.vue'
import vuetify from './src/plugins/vuetify'
import pinia, { useGlobalSettingsStore, useUserStore, useAuthStore } from './src/stores'
import i18n from './src/plugins/i18n'
import router from './router'
import ConfirmDialog from './src/composables/useConfirm'
import Toast from 'vue-toastification'
import DialogCloseBtn from './src/@core/components/DialogCloseBtn.vue'
import PageContentTitle from './src/@core/components/PageContentTitle.vue'
import api, { configure } from './runtime'
import { loadMediaSources } from './src/composables/useMediaSources'
import { loadStorageCatalog } from './src/composables/useStorageOptions'
import { loadModuleCatalog } from './src/composables/useModuleCatalog'
import { closeSharedDialog, useSharedDialog } from './src/composables/useSharedDialog'
/** 独立挂载完整原版页面；仅适配客户端、路由和初始化，不改动宿主应用。 */
export async function mount(element: HTMLElement, options: any) {
 configure(options.api, options.pluginId)
 const app = createApp(Root)
 // 使用宿主已有主题样式，避免独立Vuetify覆盖宿主同名style节点。
 vuetify.theme.install = () => {}
 app.use(pinia).use(i18n).use(vuetify).use(router).use(Toast).use(ConfirmDialog)
 app.provide('registerDynamicButton',dynamicButtonRegistry.register).provide('unregisterDynamicButton',dynamicButtonRegistry.unregister)
 app.component('VPageContentTitle',PageContentTitle).component('VDialogCloseBtn',DialogCloseBtn)
 if(options.auth) useAuthStore(pinia).$patch(options.auth)
 if(options.user) useUserStore(pinia).$patch(options.user)
 vuetify.theme.global.name.value = options.theme || 'dark'
 await router.replace('/history')
 const settings = options.settings || await api.get('system/global', {params:{token:'moviepilot'}})
 useGlobalSettingsStore(pinia).setData(settings)
 if(!options.user) {
  const user = await api.get('user/current')
  useUserStore(pinia).setSuperUser(user.is_superuser === true)
  useUserStore(pinia).setPermissions(user.permissions || {})
 }
 await Promise.all([loadMediaSources(),loadStorageCatalog(),loadModuleCatalog()])
 app.mount(element)
 return () => { for (const dialog of [...useSharedDialog().dialogs.value]) closeSharedDialog(dialog.id);app.unmount() }
}
