import { createPinia } from 'pinia'


// 创建 Pinia 实例
const pinia = createPinia()

// 使用持久化插件
// 插件挂载由宿主传入会话快照，不重复持久化宿主登录状态。

export default pinia

// 所有的 store
import { useAuthStore } from './auth'
import { useUserStore } from './user'
import { useGlobalSettingsStore } from './global'
import { usePluginSidebarNavStore } from './pluginSidebarNav'
import { usePluginRuntimeStore } from './pluginRuntime'

export { useAuthStore, useUserStore, useGlobalSettingsStore, usePluginSidebarNavStore, usePluginRuntimeStore }
