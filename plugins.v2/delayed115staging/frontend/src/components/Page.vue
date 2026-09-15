<template>
  <div class="pa-4">
    <div class="d-flex align-center ga-2 mb-3">
      <div class="text-h6">115 延迟暂存任务</div><v-spacer />
      <v-btn variant="tonal" :loading="loading" :disabled="Boolean(busy)" @click="refresh">刷新</v-btn>
    </div>
    <v-alert v-if="message" :type="messageType" variant="tonal" class="mb-3">{{ message }}</v-alert>
    <v-alert v-if="runtimeError" type="error" variant="tonal" class="mb-3">{{ runtimeError }}</v-alert>
    <v-alert type="info" variant="tonal" class="mb-3">
      新任务确认方式：{{ confirmationMode === 'staging_deleted' ? '上传器删除暂存文件后自动确认' : '手动确认 / 上传器成功回执' }}。每条任务保留登记时的确认方式。
      “已暂存”只表示硬链接已交给监控目录；取消任务保留已暂存文件，不能停止外部监控上传器。
    </v-alert>
    <v-text-field v-model="keyword" label="搜索整理根目录、媒体路径、暂存路径或任务 ID" clearable @update:model-value="page = 1" />
    <v-table density="compact">
      <thead><tr><th>媒体路径 / 任务 ID</th><th>状态 / 可暂存时间</th><th>上传 / 清理结果</th><th>操作</th></tr></thead>
      <tbody>
        <tr v-for="task in visibleTasks" :key="task.id">
          <td class="path-cell"><div>{{ task.relative_path }}</div><div class="text-caption">整理根目录：{{ task.library_root || '—' }}</div><div class="text-caption">暂存路径：{{ task.staging_path }}</div><small>{{ task.id }}</small><div v-if="task.error" class="text-error">{{ task.error }}</div></td>
          <td><v-chip size="small" class="my-1">{{ STATE_LABELS[task.state] || task.state }}</v-chip><div class="text-caption">{{ formatTime(task.ready_at) }}</div></td>
          <td class="path-cell text-caption"><div>确认方式：{{ task.confirmation_mode === 'staging_deleted' ? '暂存文件删除后自动确认' : '手动 / 成功回执' }}</div><div>上传：{{ resultText(task.upload_result) }}</div><div>清理：{{ resultText(task.cleanup_result) }}</div></td>
          <td>
            <div class="d-flex flex-wrap ga-1 py-2">
              <v-btn v-if="['failed', 'cleanup_failed'].includes(task.state)" size="small" variant="tonal" :disabled="Boolean(busy)" @click="action(task, 'retry')">重试</v-btn>
              <v-btn v-if="['waiting', 'failed', 'staged', 'linking'].includes(task.state)" size="small" variant="text" :disabled="Boolean(busy)" @click="action(task, 'cancel')">取消</v-btn>
              <v-btn v-if="task.state === 'staged'" size="small" variant="tonal" color="warning" :disabled="Boolean(busy)" @click="openConfirmation(task)">确认上传并清理</v-btn>
            </div>
          </td>
        </tr>
        <tr v-if="!visibleTasks.length"><td colspan="4" class="text-center pa-6">{{ loading ? '正在加载…' : '暂无匹配任务' }}</td></tr>
      </tbody>
    </v-table>
    <v-pagination v-if="pageCount > 1" v-model="page" :length="pageCount" :total-visible="5" />
    <div class="text-caption mt-2">共 {{ filteredTasks.length }} 条任务，时间按当前浏览器时区显示。</div>
    <div class="d-flex mt-4"><v-btn variant="text" @click="emit('switch')">配置</v-btn><v-spacer /><v-btn variant="text" @click="emit('close')">关闭</v-btn></div>
    <v-dialog v-model="confirmOpen" max-width="580" :persistent="Boolean(busy)">
      <v-card title="确认远端上传成功">
        <v-card-text>
          <p class="path-cell mb-3">整理根目录：{{ confirming?.library_root || '—' }}<br />媒体：{{ confirming?.relative_path }}<br />暂存：{{ confirming?.staging_path }}</p>
          <v-alert type="warning" variant="tonal" class="mb-3">确认后将清理暂存硬链接，并按此任务记录的清理配置处理整理硬链接。请核对远端文件名、大小及目录。</v-alert>
          <v-text-field v-model="remoteReference" label="远端文件 ID / 路径 / 上传凭据" />
          <v-checkbox v-model="verified" label="我已在 115 核验该文件上传成功，允许执行此任务的本地清理" />
        </v-card-text>
        <v-card-actions><v-btn :disabled="Boolean(busy)" @click="confirmOpen = false">返回</v-btn><v-spacer /><v-btn color="warning" :loading="Boolean(busy)" :disabled="!verified || !remoteReference.trim()" @click="confirmUpload">确认并清理</v-btn></v-card-actions>
      </v-card>
    </v-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { PLUGIN_ID, STATE_LABELS, formatTime } from './shared'

const props = defineProps({ api: { type: [Object, Function], default: () => ({}) }, pluginId: { type: String, default: PLUGIN_ID } })
const emit = defineEmits(['switch', 'action', 'close'])
const tasks = ref([])
const keyword = ref('')
const page = ref(1)
const loading = ref(false)
const busy = ref('')
const message = ref('')
const messageType = ref('info')
const runtimeError = ref('')
const confirmationMode = ref('manual')
const confirmOpen = ref(false)
const confirming = ref(null)
const remoteReference = ref('')
const verified = ref(false)
const filteredTasks = computed(() => tasks.value.filter(task => `${task.library_root || ''} ${task.relative_path} ${task.staging_path} ${task.id}`.includes(keyword.value || '')))
const pageCount = computed(() => Math.max(1, Math.ceil(filteredTasks.value.length / 20)))
const visibleTasks = computed(() => filteredTasks.value.slice((page.value - 1) * 20, page.value * 20))

function resultText(value) {
  if (value?.method === 'staging_deleted' && value.confirmed === true) return '暂存文件已删除，按上传器约定确认（未查询远端）'
  return value ? (typeof value === 'string' ? value : JSON.stringify(value)) : '—'
}

async function refresh() {
  loading.value = true
  try {
    const response = await props.api.get(`plugin/${props.pluginId || PLUGIN_ID}/tasks`)
    if (response?.success !== true) throw new Error(response?.message || '读取任务失败')
    tasks.value = response.data?.tasks || []
    runtimeError.value = response.data?.error || ''
    confirmationMode.value = response.data?.confirmation_mode || 'manual'
    page.value = Math.min(page.value, pageCount.value)
  } catch (failure) {
    messageType.value = 'error'
    message.value = failure?.message || String(failure)
  } finally {
    loading.value = false
  }
}

/** 操作结果只来自后端，接口失败时不改变本地任务状态。 */
async function action(task, operation, extra = {}) {
  if (busy.value) return false
  busy.value = task.id
  try {
    const response = await props.api.post(`plugin/${props.pluginId || PLUGIN_ID}/task`, { task_id: task.id, action: operation, ...extra })
    if (response?.success !== true) throw new Error(response?.message || '操作失败')
    messageType.value = 'success'
    message.value = response.message || '操作成功'
    emit('action', { type: operation, data: response })
    await refresh()
    return true
  } catch (failure) {
    messageType.value = 'error'
    message.value = failure?.message || String(failure)
    return false
  } finally {
    busy.value = ''
  }
}

function openConfirmation(task) {
  confirming.value = task
  remoteReference.value = ''
  verified.value = false
  confirmOpen.value = true
}

/** 必须逐任务明确核验远端，打开弹窗及暂存完成都不能自动确认。 */
async function confirmUpload() {
  if (!confirming.value || !verified.value || !remoteReference.value.trim()) return
  if (await action(confirming.value, 'confirm', { verified: true, remote_reference: remoteReference.value.trim() })) confirmOpen.value = false
}

onMounted(refresh)
</script>

<style scoped>
.path-cell { overflow-wrap: anywhere; min-width: 150px; max-width: 400px; }
</style>
