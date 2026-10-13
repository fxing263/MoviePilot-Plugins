<template>
  <div v-if="navKey" class="records-page">
    <div class="d-flex align-center pa-4"><div class="text-h6">115秒传</div></div>
    <v-alert v-if="error" type="error" variant="tonal" class="mx-4 mb-3">{{ error }}</v-alert>
    <v-alert v-if="!enabled && !loading" type="info" variant="tonal" class="mx-4 mb-3">插件已停用，仍可查看已有记录。</v-alert>
    <v-card variant="outlined" class="upload-summary mx-4 mb-4">
      <v-card-text>
        <div class="text-success d-flex align-center ga-2"><v-icon icon="mdi-cloud-upload-outline" size="20" />上传任务</div>
        <div class="text-h5 font-weight-bold mt-1">{{ tasks.length }}</div>
        <div class="text-caption text-medium-emphasis">已上传 {{ uploadedCount }} / {{ tasks.length }} 个 · {{ formatSize(uploadedBytes) }} / {{ formatSize(totalBytes) }}</div>
        <div class="d-flex flex-wrap ga-2 mt-2"><v-chip v-for="item in summary" :key="item.state" size="small" variant="tonal" :color="stateColor(item.state)">{{ item.label }} {{ item.count }}</v-chip></div>
        <div v-if="postStats && postStats.rpc_calls" class="text-caption text-medium-emphasis mt-2">CD2 刷新 RPC {{ postStats.rpc_calls }} 次 · 合并目录 {{ postStats.merged_directories || 0 }} 个 · 重试 {{ postStats.retries || 0 }} 次<br />RPC 次数不是115 API请求次数。</div>
      </v-card-text>
    </v-card>
    <v-card variant="outlined" class="queue-card mx-4">
      <v-card-item>
        <div class="d-flex flex-wrap align-center ga-2">
          <v-text-field v-model="query" placeholder="搜索文件或路径" aria-label="搜索文件或路径" prepend-inner-icon="mdi-magnify" density="compact" variant="outlined" flat single-line hide-details clearable class="record-search" />
          <v-select v-model="stateFilter" :items="stateOptions" aria-label="筛选状态" density="compact" variant="outlined" hide-details class="record-filter" />
          <v-spacer />
          <v-btn icon="mdi-refresh" variant="text" :loading="loading" aria-label="刷新队列" title="刷新队列" @click="refresh" />
        </div>

      </v-card-item>
      <v-data-table-virtual :headers="headers" :items="visibleTasks" item-value="id" :loading="loading" loading-text="正在加载队列" density="compact" fixed-header hover height="480" class="records-table">
        <template #item.file="{ item }">
          <div class="record-name py-3">
            <div class="font-weight-medium">{{ fileName(item.remote_path) }}</div>
            <small class="record-path text-medium-emphasis" :title="item.remote_path">{{ item.remote_path }}</small>
          </div>
        </template>
        <template #item.size="{ item }"><span class="text-no-wrap">{{ formatSize(item.identity?.[2]) }}</span></template>
        <template #item.ready="{ item }"><small>{{ formatTime(item.ready_at) }}</small></template>
        <template #item.state="{ item }"><v-chip size="small" :color="stateColor(item.state)" variant="tonal">{{ STATE_LABELS[item.state] || item.state }}</v-chip><small v-if="item.upload_mode === 'normal'" class="ml-2">普通上传</small></template>
        <template #item.postprocess="{ item }"><small v-if="item.postprocess">{{ POSTPROCESS_LABELS[item.postprocess.state] || item.postprocess.state }}</small><span v-else class="text-medium-emphasis">—</span></template>
        <template #item.progress="{ item }">
          <div v-if="item.state === 'running'" class="task-progress py-2">
            <div class="text-caption">{{ stageLabel(item.progress?.stage) }}</div>
            <v-progress-linear :model-value="percentage(item.progress)" :indeterminate="item.progress?.stage !== 'uploading'" color="primary" rounded height="6" aria-label="任务处理进度" />
            <div v-if="item.progress?.stage === 'uploading'" class="text-caption mt-1 text-no-wrap">{{ percentage(item.progress).toFixed(1) }}% · {{ formatSize(item.progress?.bytes_per_second) }}/s</div>
          </div>
          <span v-else class="text-medium-emphasis">—</span>
        </template>
        <template #item.actions="{ item }"><v-btn icon="mdi-dots-vertical" variant="text" size="small" aria-label="查看任务详情" title="查看任务详情" @click="openDetails(item)" /></template>
        <template #no-data>{{ tasks.length ? '没有匹配的任务' : '暂无上传任务' }}</template>
      </v-data-table-virtual>
      <v-divider />
      <div class="d-flex align-center flex-wrap ga-2 px-3 py-1">
        <v-select v-model="pageSize" :items="[25, 50, 100]" aria-label="每页条数" density="compact" variant="plain" hide-details class="page-size" />
        <span class="text-caption">{{ filteredTasks.length }} 个任务</span>
        <v-spacer />
        <v-pagination v-model="page" :length="Math.max(1, pageCount)" :total-visible="5" show-first-last-page density="compact" />
      </div>
    </v-card>
    <v-card variant="outlined" class="mx-4 mt-4" v-if="bdmv.tasks.length || bdmv.error">
      <v-card-title>BDMV · CD2 上传</v-card-title>
      <v-alert v-if="bdmv.error" type="warning" variant="tonal" class="ma-3">{{ bdmv.error }}</v-alert>
      <v-data-table :headers="bdmvHeaders" :items="bdmv.tasks" :items-per-page="10" density="compact" class="records-table">
        <template #item.name="{ item }"><div class="record-name py-2">{{ item.name }}<small class="record-path text-medium-emphasis">{{ item.downloader }} · {{ item.target }}</small></div></template>
        <template #item.state="{ item }"><v-chip size="small" :color="item.state === 'done' ? 'success' : item.state === 'blocked' ? 'error' : 'primary'">{{ bdmvLabels[item.state] || item.state }}</v-chip><small v-if="item.error" class="record-path mt-1">{{ item.error }}</small></template>
        <template #item.progress="{ item }"><div class="task-progress"><v-progress-linear :model-value="item.progress?.total_bytes ? Math.min(100, item.progress.uploaded_bytes / item.progress.total_bytes * 100) : 0" :indeterminate="['submitting', 'unknown'].includes(item.state)" color="primary" height="6" rounded /><small>{{ item.progress?.uploaded || 0 }} / {{ item.progress?.total || 0 }} 个文件 · {{ formatSize(item.progress?.uploaded_bytes) }}</small></div></template>
      </v-data-table>
    </v-card>
    <v-dialog v-model="detailsOpen" max-width="720">
      <v-card v-if="selectedTask">
        <v-card-title class="d-flex align-center">任务详情<v-spacer /><v-btn icon="mdi-close" variant="text" aria-label="关闭详情" @click="detailsOpen = false" /></v-card-title>
        <v-card-text class="record-details">
          <v-alert v-if="actionError" type="error" variant="tonal" class="mb-3">{{ actionError }}</v-alert>
          <div><strong>文件：</strong>{{ selectedTask.relative_path }}</div>
          <div><strong>状态：</strong>{{ STATE_LABELS[selectedTask.state] || selectedTask.state }}</div>
          <div><strong>115路径：</strong>{{ selectedTask.remote_path }}</div>
          <div><strong>登记时间：</strong>{{ formatTime(selectedTask.created_at) }}</div>
          <div><strong>下次尝试：</strong>{{ formatTime(selectedTask.ready_at) }}</div>
          <div v-if="selectedTask.upload_mode === 'normal'"><strong>方式：</strong>普通上传</div>
          <div><strong>尝试次数：</strong>{{ selectedTask.attempts }}</div>
          <div v-if="selectedTask.verification?.remote_bytes != null"><strong>大小校验：</strong>本地 {{ selectedTask.verification.local_bytes }} 字节 / 115 {{ selectedTask.verification.remote_bytes }} 字节</div>
          <div v-if="selectedTask.error" class="text-medium-emphasis"><strong>说明：</strong>{{ selectedTask.error }}</div>
          <template v-if="selectedTask.postprocess">
            <v-divider class="my-3" />
            <div><strong>上传后处理：</strong>{{ selectedTask.postprocess.mode === 'strm' ? '本地生成 STRM' : selectedTask.postprocess.mode === 'cd2' ? '定向刷新 CD2' : '关闭' }} · {{ POSTPROCESS_LABELS[selectedTask.postprocess.state] || selectedTask.postprocess.state }}</div>
            <div v-if="selectedTask.postprocess.target"><strong>后处理目标：</strong>{{ selectedTask.postprocess.target }}</div>
            <div><strong>后处理尝试：</strong>{{ selectedTask.postprocess.attempts || 0 }} 次 · 下次执行 {{ formatTime(selectedTask.postprocess.ready_at) }}</div>
            <div v-if="selectedTask.postprocess.error" class="text-error">{{ selectedTask.postprocess.error }}</div>
            <p class="text-caption text-medium-emphasis">使用登记时固定的模式与映射；后处理失败不会重新上传。当前配置关闭时，待处理任务暂停。</p>
          </template>
          <p v-if="postAction === 'post_enqueue'" class="text-caption text-medium-emphasis">此任务尚未执行后处理。手动补处理使用当前配置，只处理这一个任务，不重新上传。</p>
        </v-card-text>
        <v-card-actions v-if="postAction">
          <v-btn :disabled="acting || !enabled" color="primary" @click="act(postAction)">{{ postAction === 'post_retry' ? '重试后处理' : '按当前配置补处理' }}</v-btn>
        </v-card-actions>
        <v-card-actions v-if="!['running', 'uploaded'].includes(selectedTask.state)" class="flex-wrap ga-1">
          <v-btn :disabled="acting" @click="act('retry')">重新校验 / 重试</v-btn>
          <v-btn v-if="hasConflict" :disabled="acting" @click="openResolution('rename')">另存为</v-btn>
          <v-btn v-if="hasSizeConflict" :disabled="acting" color="warning" @click="openResolution('overwrite')">覆盖远端</v-btn>
          <v-btn :disabled="acting" color="error" @click="act('cancel')">取消任务</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
    <v-dialog v-model="resolutionOpen" max-width="560" :persistent="acting">
      <v-card>
        <v-card-title>{{ resolution === 'rename' ? '另存为 · 保留双方' : '确认覆盖远端文件' }}</v-card-title>
        <v-card-text class="record-details">
          <v-alert v-if="actionError" type="error" variant="tonal" class="mb-3">{{ actionError }}</v-alert>
          <div class="mb-3">{{ resolutionTask?.remote_path }}</div>
          <template v-if="resolution === 'rename'">
            <v-text-field v-model="newFilename" label="新的115文件名（含扩展名）" variant="outlined" hide-details />
            <div class="text-caption mt-2">仅修改此任务的115文件名，目录与本地文件不变。若新名称也已存在，会重新校验。</div>
          </template>
          <template v-else>
            <div>本地 {{ resolutionTask?.verification?.local_bytes }} 字节 / 115 {{ resolutionTask?.verification?.remote_bytes }} 字节</div>
            <v-alert type="warning" variant="tonal" class="mt-3">将先删除上述115文件，再上传本地文件。上传失败时原文件不会自动恢复；只有上传成功才会执行本地清理及后续标签处理。</v-alert>
          </template>
        </v-card-text>
        <v-card-actions><v-spacer />
          <v-btn :disabled="acting" @click="resolutionOpen = false">返回</v-btn>
          <v-btn :loading="acting" :color="resolution === 'overwrite' ? 'error' : 'primary'" @click="act(resolution)">{{ resolution === 'overwrite' ? '确认覆盖' : '另存并重试' }}</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { PLUGIN_ID, STATE_LABELS, POSTPROCESS_LABELS, postprocessAction, formatTime } from './shared'
const props = defineProps({ api: { type: [Object, Function], default: () => ({}) }, pluginId: { type: String, default: PLUGIN_ID }, navKey: { type: String, default: '' } })
const emit = defineEmits(['switch', 'close'])
const bdmv = ref({ tasks: [], error: '' })
const bdmvLabels = { waiting: '等待上传', submitting: '正在提交', unknown: '等待CD2确认', copying: 'CD2上传中', tagging: '正在更新标签', done: '已上传', blocked: '需要处理' }
const bdmvHeaders = [{ title: '种子 / 目标目录', key: 'name' }, { title: '状态', key: 'state' }, { title: '进度', key: 'progress', sortable: false }]
const tasks = ref([])
const postStats = ref(null)
const loading = ref(false)
const acting = ref(false)
const enabled = ref(false)
const error = ref('')
const query = ref('')
const stateFilter = ref('all')
const page = ref(1)
const pageSize = ref(25)
const detailsOpen = ref(false)
const selectedTask = ref(null)
const actionError = ref('')
const resolutionOpen = ref(false)
const resolution = ref('')
const resolutionTask = ref(null)
const newFilename = ref('')
const postAction = computed(() => postprocessAction(selectedTask.value))
const hasConflict = computed(() => selectedTask.value?.state === 'blocked' && ['size_mismatch', 'directory'].includes(selectedTask.value?.verification?.reason))
const hasSizeConflict = computed(() => hasConflict.value && selectedTask.value?.verification?.reason === 'size_mismatch')
const headers = [
  { title: '文件', key: 'file', sortable: false },
  { title: '大小', key: 'size', sortable: false, width: 110 },
  { title: '下次尝试', key: 'ready', sortable: false },
  { title: '状态', key: 'state', sortable: false },
  { title: '上传后处理', key: 'postprocess', sortable: false },
  { title: '进度 / 速度', key: 'progress', sortable: false, width: 210 },
  { title: '', key: 'actions', sortable: false },
]
const stateOptions = [{ title: '全部状态', value: 'all' }, ...Object.entries(STATE_LABELS).map(([value, title]) => ({ title, value }))]
const summary = computed(() => Object.entries(STATE_LABELS).map(([state, label]) => ({ state, label, count: tasks.value.filter(task => task.state === state).length })).filter(item => item.count))
const filteredTasks = computed(() => tasks.value.filter(task =>
  (stateFilter.value === 'all' || task.state === stateFilter.value) &&
  (!query.value || `${task.remote_path}`.toLowerCase().includes(query.value.trim().toLowerCase()))
))
const pageCount = computed(() => Math.ceil(filteredTasks.value.length / pageSize.value))
const visibleTasks = computed(() => filteredTasks.value.slice((page.value - 1) * pageSize.value, page.value * pageSize.value))
watch([query, stateFilter, pageSize], () => { page.value = 1 })
const uploadedCount = computed(() => tasks.value.filter(task => task.state === 'uploaded').length)
const totalBytes = computed(() => tasks.value.reduce((sum, task) => sum + (task.identity?.[2] || 0), 0))
const uploadedBytes = computed(() => tasks.value.filter(task => task.state === 'uploaded').reduce((sum, task) => sum + (task.identity?.[2] || 0), 0))
function formatSize(value) {
  if (!value) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  const index = Math.min(Math.floor(Math.log(value) / Math.log(1024)), units.length - 1)
  return `${(value / 1024 ** index).toFixed(index ? 1 : 0)} ${units[index]}`
}
function percentage(progress) {
  return progress?.total_bytes > 0 ? Math.min(100, Math.max(0, progress.completed_bytes / progress.total_bytes * 100)) : 0
}
function stageLabel(stage) {
  return { hashing: '计算文件哈希', checking: '检查秒传', uploading: '普通上传', verifying: '提交并校验远端文件' }[stage] || '正在处理'
}
function fileName(path) {
  return path?.split('/').pop() || path
}
function openDetails(task) {
  actionError.value = ''
  selectedTask.value = task
  detailsOpen.value = true
}
function stateColor(state) {
  if (['blocked'].includes(state)) return 'error'
  if (state === 'uploaded') return 'success'
  if (state === 'waiting' || state === 'running') return 'warning'
  return 'primary'
}
function openResolution(action) {
  resolution.value = action
  resolutionTask.value = JSON.parse(JSON.stringify(selectedTask.value))
  const name = fileName(selectedTask.value.remote_path)
  const dot = name.lastIndexOf('.')
  newFilename.value = dot > 0 ? `${name.slice(0, dot)} (本地)${name.slice(dot)}` : `${name} (本地)`
  actionError.value = ''
  resolutionOpen.value = true
}
async function act(action) {
  acting.value = true
  actionError.value = ''
  try {
    const conflictAction = ['rename', 'overwrite'].includes(action)
    const task = conflictAction ? resolutionTask.value : selectedTask.value
    const payload = { task_id: task.id, action }
    if (conflictAction) Object.assign(payload, { verification: task.verification, filename: newFilename.value, confirmed: action === 'overwrite' })
    const response = await props.api.post(`plugin/${props.pluginId || PLUGIN_ID}/task`, payload)
    if (response?.success !== true) throw new Error(response?.message || '操作失败')
    detailsOpen.value = false
    resolutionOpen.value = false
    await refresh()
  } catch (failure) { actionError.value = failure?.message || String(failure) }
  finally { acting.value = false }
}
async function refresh() {
  if (loading.value) return
  loading.value = true
  error.value = ''
  try {
    const response = await props.api.get(`plugin/${props.pluginId || PLUGIN_ID}/tasks`)
    if (response?.success !== true) throw new Error(response?.message || '读取状态失败')
    tasks.value = response.data?.tasks || []
    postStats.value = response.data?.postprocess_stats || null
    bdmv.value = response.data?.bdmv || { tasks: [], error: '' }
    if (page.value > pageCount.value) page.value = Math.max(1, pageCount.value)
    if (selectedTask.value) selectedTask.value = tasks.value.find(task => task.id === selectedTask.value.id) || null
    enabled.value = response.data?.enabled === true
    error.value = response.data?.error || ''
  } catch (failure) {
    error.value = failure?.message || String(failure)
  } finally {
    loading.value = false
  }
}
let refreshTimer
let idleTicks = 0
onMounted(() => {
  // 插件卡片入口交给宿主打开配置；只有独立侧栏页查询和轮询上传队列。
  if (!props.navKey) {
    emit('switch')
    return
  }
  refresh()
  refreshTimer = setInterval(() => { if (!document.hidden && (tasks.value.some(task => task.state === 'running') || ++idleTicks >= 5)) { idleTicks = 0; refresh() } }, 3000)
})
onUnmounted(() => clearInterval(refreshTimer))
</script>

<style scoped>
.records-page { min-width: 0; }
.task-progress { min-width: 170px; }
.record-search { min-width: 180px; flex: 1; }
.record-filter { min-width: 150px; max-width: 190px; }
.records-table :deep(table) { min-width: 620px; }
.upload-summary { border-top: 3px solid rgb(var(--v-theme-success)); border-radius: 6px; }
.queue-card { border-radius: 6px; }
.record-name { min-width: 220px; overflow-wrap: anywhere; }
.record-path { display: block; overflow-wrap: anywhere; line-height: 1.6; }
.page-size { max-width: 76px; }
.record-details { overflow-wrap: anywhere; line-height: 1.9; }
</style>
