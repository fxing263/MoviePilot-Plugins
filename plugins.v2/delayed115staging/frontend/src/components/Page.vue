<template>
  <div class="pa-4">
    <div class="d-flex align-center mb-4"><div class="text-h6">115 延迟暂存</div><v-spacer /><v-btn :loading="loading" @click="refresh">刷新</v-btn></div>
    <v-alert v-if="error" type="error" variant="tonal" class="mb-4">{{ error }}</v-alert>
    <v-alert type="info" variant="tonal" class="mb-4">{{ enabled ? '自动处理已启用' : '插件已停用' }}。硬链接创建、删除和异常详情请查看插件日志。</v-alert>
    <div class="d-flex flex-wrap ga-3"><v-chip v-for="item in summary" :key="item.state">{{ item.label }}：{{ item.count }}</v-chip></div>
    <v-alert v-if="failedCount" type="warning" variant="tonal" class="mt-4">有 {{ failedCount }} 项异常，请查看日志排查。</v-alert>
    <div class="d-flex mt-4"><v-btn variant="text" @click="emit('switch')">配置</v-btn><v-spacer /><v-btn variant="text" @click="emit('close')">关闭</v-btn></div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { PLUGIN_ID, STATE_LABELS } from './shared'
const props = defineProps({ api: { type: [Object, Function], default: () => ({}) }, pluginId: { type: String, default: PLUGIN_ID } })
const emit = defineEmits(['switch', 'close'])
const tasks = ref([])
const loading = ref(false)
const enabled = ref(false)
const error = ref('')
const summary = computed(() => Object.entries(STATE_LABELS).map(([state, label]) => ({ state, label, count: tasks.value.filter(task => task.state === state).length })).filter(item => item.count))
const failedCount = computed(() => tasks.value.filter(task => task.error || ['failed', 'cleanup_failed'].includes(task.state)).length)
async function refresh() {
  if (loading.value) return
  loading.value = true
  error.value = ''
  try {
    const response = await props.api.get(`plugin/${props.pluginId || PLUGIN_ID}/tasks`)
    if (response?.success !== true) throw new Error(response?.message || '读取状态失败')
    tasks.value = response.data?.tasks || []
    enabled.value = response.data?.enabled === true
    error.value = response.data?.error || ''
  } catch (failure) {
    error.value = failure?.message || String(failure)
  } finally {
    loading.value = false
  }
}
onMounted(refresh)
</script>
