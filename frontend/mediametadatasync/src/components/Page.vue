<template>
  <div class="plugin-workbench sync-console">
    <header class="console-header">
      <div class="identity-block">
        <div class="identity-row">
          <div class="text-h6">媒体元数据双目录同步</div>
          <span class="status-pill" :class="statusTone">
            <span class="status-dot" />
            {{ statusLabel }}
          </span>
        </div>
        <div class="header-meta">
          <span>{{ taskLabel }}</span>
          <span v-if="state.task_finished_at">{{ formatTime(state.task_finished_at) }}</span>
        </div>
      </div>
      <div class="header-actions">
        <v-btn
          icon="mdi-refresh"
          variant="text"
          size="small"
          title="刷新"
          aria-label="刷新插件状态"
          :loading="refreshing"
          @click="refreshAll"
        />
        <v-btn icon="mdi-cog" variant="text" size="small" title="设置" aria-label="打开插件设置" @click="emit('switch')" />
        <v-btn icon="mdi-close" variant="text" size="small" title="关闭" aria-label="关闭插件页面" @click="emit('close')" />
      </div>
    </header>

    <v-divider />

    <div v-if="initialLoading" class="initial-loading">
      <v-progress-circular indeterminate color="primary" size="26" width="2" />
      <span>正在读取插件状态</span>
    </div>

    <template v-else>
      <div class="task-banner" :class="statusTone" aria-live="polite" aria-atomic="true">
        <v-progress-circular v-if="taskBusy" indeterminate size="18" width="2" />
        <v-icon
          v-else
          :icon="state.last_error ? 'mdi-alert-circle-outline' : 'mdi-information-outline'"
          size="20"
        />
        <span>{{ state.last_error || state.task_message || taskLabel }}</span>
      </div>

      <v-tabs v-model="activeView" class="view-tabs" color="primary" show-arrows>
        <v-tab value="sync" prepend-icon="mdi-folder-sync-outline">同步</v-tab>
        <v-tab value="missing" prepend-icon="mdi-file-alert-outline">
          缺失元数据
          <span v-if="missingTotal" class="tab-count warning">{{ missingTotal }}</span>
        </v-tab>
        <v-tab value="activity" prepend-icon="mdi-text-box-outline">
          运行记录
          <span v-if="state.not_ready.length" class="tab-count">{{ state.not_ready.length }}</span>
        </v-tab>
      </v-tabs>

      <v-divider />

      <main class="console-body">
        <v-window v-model="activeView">
          <v-window-item value="sync">
            <section class="metric-grid" aria-label="同步状态概览">
              <div v-for="metric in syncMetrics" :key="metric.label" class="metric-cell">
                <v-icon :icon="metric.icon" :color="metric.color" size="20" />
                <div>
                  <div class="metric-value">{{ metric.value }}</div>
                  <div class="metric-label">{{ metric.label }}</div>
                </div>
              </div>
            </section>

            <section class="command-section">
              <div class="section-heading">
                <div>
                  <div class="text-subtitle-2">同步任务</div>
                  <div class="section-meta">{{ taskAvailability }}</div>
                </div>
                <span class="monitor-state" :class="state.monitoring ? 'active' : ''">
                  <v-icon :icon="state.monitoring ? 'mdi-radar' : 'mdi-radar-off'" size="17" />
                  {{ monitorLabel }}
                </span>
              </div>
              <div class="command-grid">
                <v-btn
                  color="primary"
                  prepend-icon="mdi-sync"
                  :loading="activeAction === 'all'"
                  :disabled="actionDisabled"
                  @click="submitAction('all')"
                >
                  双向全量
                </v-btn>
                <v-btn
                  color="primary"
                  variant="outlined"
                  prepend-icon="mdi-folder-arrow-right-outline"
                  :loading="activeAction === 'forward'"
                  :disabled="actionDisabled"
                  @click="submitAction('forward')"
                >
                  正向全量
                </v-btn>
                <v-btn
                  color="secondary"
                  variant="outlined"
                  prepend-icon="mdi-code-json"
                  :loading="activeAction === 'reverse'"
                  :disabled="actionDisabled"
                  @click="submitAction('reverse')"
                >
                  JSON 回写
                </v-btn>
                <v-btn
                  v-if="state.monitoring"
                  color="warning"
                  variant="text"
                  prepend-icon="mdi-stop"
                  :loading="activeAction === 'monitor-stop'"
                  :disabled="!!activeAction"
                  @click="submitAction('monitor-stop')"
                >
                  停止监控
                </v-btn>
                <v-btn
                  v-else
                  color="success"
                  variant="text"
                  prepend-icon="mdi-play"
                  :loading="activeAction === 'monitor-start'"
                  :disabled="monitorStartDisabled"
                  @click="submitAction('monitor-start')"
                >
                  启动监控
                </v-btn>
              </div>
            </section>

            <section class="path-section">
              <div class="path-item">
                <v-icon icon="mdi-folder-arrow-right-outline" color="primary" size="20" />
                <span class="path-label">9kg</span>
                <code>{{ sourcePath || '-' }}</code>
              </div>
              <v-icon class="path-arrow" icon="mdi-arrow-right" size="18" />
              <div class="path-item">
                <v-icon icon="mdi-folder-arrow-left-right-outline" color="secondary" size="20" />
                <span class="path-label">番号系列</span>
                <code>{{ targetPath || '-' }}</code>
              </div>
            </section>

            <section class="workspace-grid">
              <div class="workspace-panel">
                <div class="panel-heading">最近任务</div>
                <div class="detail-list">
                  <div class="detail-row"><span>类型</span><strong>{{ taskKindLabel }}</strong></div>
                  <div class="detail-row"><span>状态</span><strong>{{ taskStatusLabel }}</strong></div>
                  <div class="detail-row"><span>开始</span><strong>{{ formatTime(state.task_started_at) || '-' }}</strong></div>
                  <div class="detail-row"><span>结束</span><strong>{{ formatTime(state.task_finished_at) || '-' }}</strong></div>
                </div>
              </div>
              <div class="workspace-panel">
                <div class="panel-heading">分类目录</div>
                <div v-if="categoryStats.length" class="detail-list">
                  <div v-for="item in categoryStats" :key="item.name" class="detail-row">
                    <span>{{ item.name }}</span><strong>{{ item.value }}</strong>
                  </div>
                </div>
                <div v-else class="panel-empty">暂无分类统计</div>
              </div>
            </section>
          </v-window-item>

          <v-window-item value="missing">
            <section class="missing-toolbar">
              <div class="missing-summary-copy">
                <div class="text-subtitle-2">缺失元数据</div>
                <div class="section-meta">{{ missingSummaryText }}</div>
              </div>
              <div class="missing-tools">
                <v-text-field
                  v-model="missingQuery"
                  class="missing-search"
                  density="compact"
                  variant="outlined"
                  hide-details
                  clearable
                  prepend-inner-icon="mdi-magnify"
                  label="搜索番号或路径"
                />
                <v-btn
                  color="primary"
                  prepend-icon="mdi-database-search-outline"
                  :loading="state.task_kind === 'missing_scan' && taskBusy"
                  :disabled="actionDisabled"
                  @click="scanMissingMetadata"
                >
                  开始检查
                </v-btn>
              </div>
            </section>

            <section class="missing-metrics">
              <div><strong>{{ missingTotal }}</strong><span>缺失记录</span></div>
              <div><strong>{{ missingSummary.missing_nfo || 0 }}</strong><span>缺少 NFO</span></div>
              <div><strong>{{ missingSummary.missing_mediainfo || 0 }}</strong><span>缺少 MediaInfo</span></div>
              <div><strong>{{ missingSummary.scanned_strm_files || 0 }}</strong><span>已检查 STRM</span></div>
            </section>

            <section v-if="missingDeleteReport" class="delete-report" :class="missingDeleteReport.success ? 'success' : 'error'">
              <v-icon :icon="missingDeleteReport.success ? 'mdi-check-circle-outline' : 'mdi-alert-circle-outline'" size="20" />
              <div>
                <strong>{{ missingDeleteReport.message }}</strong>
                <span>{{ deleteReportSummary }}</span>
              </div>
            </section>

            <div v-if="missingLoading" class="inline-loading">
              <v-progress-circular indeterminate size="22" width="2" color="primary" />
              <span>正在读取检查结果</span>
            </div>
            <div v-else-if="!missingItems.length" class="empty-state">
              <v-icon icon="mdi-file-check-outline" size="38" color="success" />
              <strong>{{ missingQuery ? '没有匹配结果' : '暂无缺失元数据记录' }}</strong>
            </div>
            <div v-else class="missing-table">
              <div class="missing-head">
                <span>番号 / 文件</span>
                <span>缺失项</span>
                <span>9kg 位置</span>
                <span>网盘</span>
                <span />
              </div>
              <div v-for="item in missingItems" :key="item.item_id" class="missing-row">
                <div class="file-cell">
                  <strong>{{ item.number }}</strong>
                  <span>{{ item.file_name }}</span>
                </div>
                <div class="missing-chip-cell">
                  <v-chip
                    v-for="type in item.missing_types"
                    :key="type"
                    size="x-small"
                    color="warning"
                    variant="tonal"
                  >
                    {{ type }}
                  </v-chip>
                </div>
                <div class="source-cell">
                  <span>{{ ownerLabel(item) }}</span>
                  <small>{{ item.source_paths.length }} 个源位置</small>
                </div>
                <div class="cloud-cell" :class="item.cloud_ready ? 'ready' : 'blocked'">
                  <v-icon :icon="item.cloud_ready ? 'mdi-cloud-check-outline' : 'mdi-cloud-alert-outline'" size="18" />
                  <span>{{ item.cloud_ready ? '可定位' : '不可删除' }}</span>
                </div>
                <v-btn
                  icon="mdi-delete-outline"
                  color="error"
                  variant="text"
                  size="small"
                  title="预览并删除"
                  :disabled="taskBusy || !!activeAction"
                  @click="openDeletePreview(item)"
                />
              </div>
            </div>

            <v-pagination
              v-if="missingPageCount > 1"
              v-model="missingPage"
              :length="missingPageCount"
              density="comfortable"
              class="pagination"
              @update:model-value="loadMissingItems"
            />
          </v-window-item>

          <v-window-item value="activity">
            <section class="activity-grid">
              <div class="activity-panel">
                <div class="panel-heading">
                  <span>待就绪目录</span>
                  <span class="heading-count">{{ state.not_ready.length }}</span>
                </div>
                <div v-if="state.not_ready.length" class="activity-list">
                  <div v-for="item in state.not_ready" :key="item.path" class="activity-row">
                    <v-icon icon="mdi-clock-outline" color="warning" size="19" />
                    <div>
                      <code>{{ item.path }}</code>
                      <span>{{ item.reason }}</span>
                    </div>
                  </div>
                </div>
                <div v-else class="panel-empty">当前没有待就绪目录</div>
              </div>
              <div class="activity-panel">
                <div class="panel-heading">运行日志</div>
                <div v-if="state.logs.length" class="log-list">
                  <code v-for="(line, index) in state.logs" :key="`${index}-${line}`">{{ line }}</code>
                </div>
                <div v-else class="panel-empty">暂无运行日志</div>
              </div>
            </section>
          </v-window-item>
        </v-window>
      </main>
    </template>

    <v-dialog v-model="deleteDialog.show" max-width="720" persistent>
      <v-card class="delete-dialog">
        <v-card-title class="dialog-header">
          <div>
            <div class="text-subtitle-1 font-weight-medium">三端删除确认</div>
            <div class="text-caption text-medium-emphasis">
              {{ deleteDialog.item?.number }} / {{ deleteDialog.item?.file_name }}
            </div>
          </div>
          <v-btn
            icon="mdi-close"
            variant="text"
            size="small"
            title="关闭"
            :disabled="deleteDialog.submitting"
            @click="closeDeleteDialog"
          />
        </v-card-title>
        <v-divider />
        <v-card-text class="dialog-content">
          <div v-if="deleteDialog.loading" class="inline-loading dialog-loading">
            <v-progress-circular indeterminate size="24" width="2" color="primary" />
            <span>正在生成删除清单</span>
          </div>
          <template v-else-if="deleteDialog.plan">
            <v-alert
              v-if="deleteDialog.plan.blocked_reasons.length"
              type="error"
              variant="tonal"
              density="compact"
            >
              {{ deleteDialog.plan.blocked_reasons.join('；') }}
            </v-alert>
            <v-alert v-else type="warning" variant="tonal" density="compact">
              删除按网盘源文件、番号系列、9kg 顺序执行，前一步复核失败会停止后续处理。
            </v-alert>

            <div class="delete-stage-list">
              <div v-for="stage in deletePreviewStages" :key="stage.key" class="delete-stage">
                <div class="stage-heading">
                  <v-icon :icon="stage.icon" :color="stage.color" size="20" />
                  <strong>{{ stage.label }}</strong>
                  <span>{{ stage.files.length }} 个文件</span>
                </div>
                <div v-if="stage.files.length" class="stage-files">
                  <code v-for="path in stage.files.slice(0, 5)" :key="path">{{ path }}</code>
                  <span v-if="stage.files.length > 5" class="more-files">
                    另有 {{ stage.files.length - 5 }} 个文件
                  </span>
                </div>
                <div v-else class="stage-empty">当前无对应文件</div>
              </div>
            </div>

            <v-checkbox
              v-model="deleteDialog.confirmed"
              color="error"
              hide-details
              label="我已核对以上删除目标"
              :disabled="deleteDialog.plan.blocked_reasons.length > 0"
            />
          </template>
        </v-card-text>
        <v-divider />
        <v-card-actions class="dialog-actions">
          <v-btn variant="text" :disabled="deleteDialog.submitting" @click="closeDeleteDialog">取消</v-btn>
          <v-btn
            color="error"
            prepend-icon="mdi-delete-alert-outline"
            :loading="deleteDialog.submitting"
            :disabled="!deleteReady"
            @click="submitMissingDelete"
          >
            确认三端删除
          </v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <v-snackbar v-model="snackbar.show" :color="snackbar.color" timeout="4500">
      {{ snackbar.text }}
    </v-snackbar>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'

import { MEDIA_METADATA_SYNC_PLUGIN_ID } from '../utils/pluginId.js'

const props = defineProps({
  api: {
    type: [Object, Function],
    required: true,
  },
  initialConfig: {
    type: Object,
    default: () => ({}),
  },
})

const emit = defineEmits(['close', 'switch', 'update:config', 'action'])
const pluginId = MEDIA_METADATA_SYNC_PLUGIN_ID
const initialLoading = ref(true)
const refreshing = ref(false)
const missingLoading = ref(false)
const activeView = ref('sync')
const activeAction = ref('')
const missingQuery = ref('')
const missingPage = ref(1)
const missingPageCount = ref(1)
const missingItems = ref([])
const missingListTotal = ref(0)
const snackbar = reactive({ show: false, text: '', color: 'info' })
const state = reactive(createInitialState())
const missingListSummary = reactive({})
const deleteDialog = reactive({
  show: false,
  item: null,
  loading: false,
  submitting: false,
  confirmed: false,
  plan: null,
})
let pollTimer = null
let searchTimer = null
let lastObservedTask = ''

function createInitialState() {
  return {
    enabled: false,
    monitor_enabled: false,
    reverse_sync_enabled: true,
    monitoring: false,
    task_status: 'idle',
    task_kind: '',
    task_message: '',
    task_started_at: '',
    task_finished_at: '',
    last_error: '',
    pending_source_count: 0,
    pending_json_count: 0,
    activated_count: 0,
    not_ready: [],
    stats: {},
    logs: [],
    config: { source_dir: '', target_dir: '' },
    last_report: {},
    missing_metadata: {},
  }
}

const busyStatuses = new Set(['queued', 'pending', 'starting', 'running', 'scanning', 'syncing', 'working', 'in_progress'])
const failedStatuses = new Set(['failed', 'error'])
const taskStatus = computed(() => String(state.task_status || 'idle').toLowerCase())
const taskBusy = computed(() => busyStatuses.has(taskStatus.value))
const taskFailed = computed(() => failedStatuses.has(taskStatus.value))
const statusTone = computed(() => {
  if (taskFailed.value) return 'error'
  if (taskBusy.value) return 'working'
  if (!state.enabled) return 'muted'
  return state.monitoring ? 'success' : 'idle'
})
const statusLabel = computed(() => {
  if (!state.enabled) return '未启用'
  if (taskFailed.value) return '任务失败'
  if (taskBusy.value) return '任务执行中'
  if (state.monitoring) return '实时监控中'
  return '空闲'
})
const taskKindLabel = computed(() => ({
  sync_all: '双向全量同步',
  sync_forward: '正向全量同步',
  sync_reverse: 'JSON 全量回写',
  startup_sync: '启动双向全量同步',
  monitor_start: '全量同步后启动监控',
  missing_scan: '缺失元数据扫描',
  missing_delete: '缺失记录三端删除',
}[state.task_kind] || state.task_kind || '暂无任务'))
const taskStatusLabel = computed(() => ({
  idle: '空闲',
  queued: '排队中',
  running: '执行中',
  succeeded: '已完成',
  completed: '已完成',
  success: '已完成',
  failed: '失败',
  stopped: '已停止',
}[taskStatus.value] || state.task_status || '空闲'))
const taskLabel = computed(() => state.task_message || taskKindLabel.value)
const sourcePath = computed(() => state.config?.source_dir || props.initialConfig.source_dir || '')
const targetPath = computed(() => state.config?.target_dir || props.initialConfig.target_dir || '')
const monitorLabel = computed(() => state.monitoring ? '监控运行中' : state.monitor_enabled ? '监控已停止' : '监控未启用')
const taskAvailability = computed(() => state.enabled ? taskBusy.value ? taskLabel.value : '可提交新的后台任务' : '插件未启用')
const actionDisabled = computed(() => !state.enabled || taskBusy.value || !!activeAction.value)
const monitorStartDisabled = computed(() => actionDisabled.value || !state.monitor_enabled)
const missingSummary = computed(() => Object.keys(missingListSummary).length ? missingListSummary : state.missing_metadata || {})
const missingTotal = computed(() => Number(missingListTotal.value || missingSummary.value.missing_items || 0))
const missingSummaryText = computed(() => {
  if (!missingSummary.value.generated_at) return '尚未执行检查'
  return `${formatTime(missingSummary.value.generated_at)} · ${missingSummary.value.message || '检查完成'}`
})
const categoryStats = computed(() => Object.entries(state.stats || {}).map(([name, value]) => ({ name, value })))
const syncMetrics = computed(() => [
  { label: '待处理源事件', value: state.pending_source_count, icon: 'mdi-folder-clock-outline', color: 'warning' },
  { label: '待回写 JSON', value: state.pending_json_count, icon: 'mdi-code-json', color: 'secondary' },
  { label: '已激活目录', value: state.activated_count, icon: 'mdi-folder-check-outline', color: 'success' },
  { label: '未就绪目录', value: state.not_ready.length, icon: 'mdi-folder-alert-outline', color: state.not_ready.length ? 'warning' : 'success' },
])
const missingDeleteReport = computed(() => state.last_report?.kind === 'missing_delete' ? state.last_report : null)
const deleteReportSummary = computed(() => {
  const report = missingDeleteReport.value
  if (!report) return ''
  return [
    `网盘 ${verifiedCount(report.cloud_results)}/${report.cloud_results?.length || 0}`,
    `番号系列 ${verifiedCount(report.target_results)}/${report.target_results?.length || 0}`,
    `9kg ${verifiedCount(report.source_results)}/${report.source_results?.length || 0}`,
  ].join(' · ')
})
const deletePreviewStages = computed(() => {
  const plan = deleteDialog.plan || {}
  return [
    { key: 'cloud', label: '网盘源文件', files: plan.cloud_files || [], icon: 'mdi-cloud-remove-outline', color: 'error' },
    { key: 'target', label: '番号系列', files: plan.target_files || [], icon: 'mdi-folder-arrow-left-right-outline', color: 'secondary' },
    { key: 'source', label: '9kg', files: plan.source_files || [], icon: 'mdi-folder-arrow-right-outline', color: 'primary' },
  ]
})
const deleteReady = computed(() => Boolean(
  deleteDialog.plan
  && !deleteDialog.loading
  && !deleteDialog.submitting
  && deleteDialog.confirmed
  && deleteDialog.plan.confirm_token
  && !deleteDialog.plan.blocked_reasons?.length
))

const normalizeSuccess = (result) => {
  if (!result || typeof result !== 'object') return false
  if (typeof result.success === 'boolean') return result.success
  if (Object.prototype.hasOwnProperty.call(result, 'code')) return Number(result.code) === 0
  return true
}

const resultMessage = (result, fallback = '') => result?.message || result?.msg || fallback

const request = async (method, url) => {
  if (typeof props.api === 'function') return props.api({ method: method.toUpperCase(), url })
  const handler = props.api?.[method]
  if (typeof handler !== 'function') throw new Error('页面 API 未就绪')
  return handler.call(props.api, url)
}

const showMessage = (text, color = 'info') => {
  snackbar.text = text
  snackbar.color = color
  snackbar.show = true
}

const formatTime = (value) => {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value).replace('T', ' ')
  return date.toLocaleString('zh-CN', { hour12: false })
}

const verifiedCount = (results) => (results || []).filter((item) => item.verified).length
const ownerLabel = (item) => (item.owner_names || []).slice(0, 2).join('、') || '-'

const loadState = async ({ silent = false } = {}) => {
  if (!silent) refreshing.value = true
  try {
    const result = await request('get', `plugin/${pluginId}/status`)
    if (!normalizeSuccess(result)) throw new Error(resultMessage(result, '读取插件状态失败'))
    const previousBusy = taskBusy.value
    Object.assign(state, createInitialState(), result.data || {})
    state.not_ready = Array.isArray(state.not_ready) ? state.not_ready : []
    state.logs = Array.isArray(state.logs) ? state.logs : []
    state.stats = state.stats && typeof state.stats === 'object' ? state.stats : {}
    const currentTask = `${state.task_kind}:${state.task_status}:${state.task_finished_at}`
    if (previousBusy && !taskBusy.value && currentTask !== lastObservedTask) {
      lastObservedTask = currentTask
      activeAction.value = ''
      if (state.task_kind === 'missing_scan' || state.task_kind === 'missing_delete') {
        await loadMissingItems({ silent: true })
      }
      showMessage(state.task_message || '后台任务已结束', taskFailed.value ? 'error' : 'success')
    }
  } catch (error) {
    showMessage(error?.message || '读取插件状态失败', 'error')
  } finally {
    initialLoading.value = false
    if (!silent) refreshing.value = false
    schedulePoll(taskBusy.value ? 1000 : state.monitoring ? 3500 : 6000)
  }
}

const loadMissingItems = async ({ silent = false } = {}) => {
  if (!silent) missingLoading.value = true
  try {
    const query = new URLSearchParams({
      page: String(missingPage.value),
      page_size: '30',
      query: missingQuery.value || '',
    })
    const result = await request('get', `plugin/${pluginId}/missing/items?${query.toString()}`)
    if (!normalizeSuccess(result)) throw new Error(resultMessage(result, '读取缺失元数据失败'))
    const data = result.data || {}
    missingItems.value = Array.isArray(data.items) ? data.items : []
    missingListTotal.value = Number(data.total || 0)
    missingPage.value = Number(data.page || 1)
    missingPageCount.value = Number(data.page_count || 1)
    for (const key of Object.keys(missingListSummary)) delete missingListSummary[key]
    Object.assign(missingListSummary, data.summary || {})
  } catch (error) {
    showMessage(error?.message || '读取缺失元数据失败', 'error')
  } finally {
    if (!silent) missingLoading.value = false
  }
}

const refreshAll = async () => {
  await loadState()
  if (activeView.value === 'missing') await loadMissingItems()
}

const schedulePoll = (delay) => {
  if (pollTimer) window.clearTimeout(pollTimer)
  pollTimer = window.setTimeout(() => loadState({ silent: true }), delay)
}

const submitAction = async (action) => {
  const actions = {
    all: { endpoint: 'sync/all', label: '双向全量同步' },
    forward: { endpoint: 'sync/forward', label: '正向全量同步' },
    reverse: { endpoint: 'sync/reverse', label: 'JSON 回写' },
    'monitor-start': { endpoint: 'monitor/start', label: '启动实时监控' },
    'monitor-stop': { endpoint: 'monitor/stop', label: '停止实时监控' },
  }
  const selected = actions[action]
  if (!selected) return
  activeAction.value = action
  try {
    const result = await request('post', `plugin/${pluginId}/${selected.endpoint}`)
    if (!normalizeSuccess(result)) throw new Error(resultMessage(result, `${selected.label}提交失败`))
    state.task_status = result.data?.status || 'queued'
    state.task_kind = action
    state.task_message = resultMessage(result, `${selected.label}已提交`)
    showMessage(state.task_message, 'info')
    emit('action', { action, response: result })
    schedulePoll(500)
  } catch (error) {
    activeAction.value = ''
    showMessage(error?.message || `${selected.label}提交失败`, 'error')
  }
}

const scanMissingMetadata = async () => {
  activeAction.value = 'missing-scan'
  try {
    const result = await request('post', `plugin/${pluginId}/missing/scan`)
    if (!normalizeSuccess(result)) throw new Error(resultMessage(result, '检查任务提交失败'))
    state.task_status = result.data?.status || 'queued'
    state.task_kind = 'missing_scan'
    state.task_message = resultMessage(result, '缺失元数据检查已提交')
    showMessage(state.task_message, 'info')
    schedulePoll(500)
  } catch (error) {
    activeAction.value = ''
    showMessage(error?.message || '检查任务提交失败', 'error')
  }
}

const openDeletePreview = async (item) => {
  Object.assign(deleteDialog, {
    show: true,
    item,
    loading: true,
    submitting: false,
    confirmed: false,
    plan: null,
  })
  try {
    const query = new URLSearchParams({ item_id: item.item_id })
    const result = await request('get', `plugin/${pluginId}/missing/delete-preview?${query.toString()}`)
    if (!normalizeSuccess(result)) throw new Error(resultMessage(result, '生成删除预览失败'))
    deleteDialog.plan = result.data || null
  } catch (error) {
    showMessage(error?.message || '生成删除预览失败', 'error')
    deleteDialog.show = false
  } finally {
    deleteDialog.loading = false
  }
}

const closeDeleteDialog = () => {
  if (deleteDialog.submitting) return
  deleteDialog.show = false
}

const submitMissingDelete = async () => {
  if (!deleteReady.value || !deleteDialog.item) return
  deleteDialog.submitting = true
  try {
    const query = new URLSearchParams({
      item_id: deleteDialog.item.item_id,
      confirmed: 'true',
      confirm_token: deleteDialog.plan.confirm_token,
    })
    const result = await request('post', `plugin/${pluginId}/missing/delete?${query.toString()}`)
    if (!normalizeSuccess(result)) throw new Error(resultMessage(result, '删除任务提交失败'))
    state.task_status = result.data?.status || 'queued'
    state.task_kind = 'missing_delete'
    state.task_message = resultMessage(result, '三端删除任务已提交')
    activeAction.value = 'missing-delete'
    deleteDialog.show = false
    showMessage(state.task_message, 'info')
    schedulePoll(500)
  } catch (error) {
    showMessage(error?.message || '删除任务提交失败', 'error')
  } finally {
    deleteDialog.submitting = false
  }
}

watch(activeView, (value) => {
  if (value === 'missing') loadMissingItems()
})

watch(missingQuery, () => {
  missingPage.value = 1
  if (searchTimer) window.clearTimeout(searchTimer)
  searchTimer = window.setTimeout(() => loadMissingItems(), 350)
})

onMounted(async () => {
  await loadState()
  await loadMissingItems({ silent: true })
})

onBeforeUnmount(() => {
  if (pollTimer) window.clearTimeout(pollTimer)
  if (searchTimer) window.clearTimeout(searchTimer)
})
</script>

<style scoped>
.plugin-workbench,
.delete-dialog {
  --mms-surface: rgb(var(--v-theme-surface));
  --mms-subtle: rgba(var(--v-theme-surface-variant), 0.28);
  --mms-hover: rgba(var(--v-theme-primary), 0.06);
  --mms-text: rgb(var(--v-theme-on-surface));
  --mms-muted: rgba(var(--v-theme-on-surface), 0.72);
  --mms-border: rgba(var(--v-border-color), var(--v-border-opacity));
  --mms-border-soft: rgba(var(--v-border-color), 0.18);
  --mms-accent: rgb(var(--v-theme-primary));
  --mms-secondary: rgb(var(--v-theme-secondary));
  --mms-success: rgb(var(--v-theme-success));
  --mms-warning: rgb(var(--v-theme-warning));
  --mms-danger: rgb(var(--v-theme-error));
  --mms-info: rgb(var(--v-theme-info));
  --mms-chip-bg: rgba(var(--v-theme-on-surface), 0.1);
  --mms-info-soft: rgba(var(--v-theme-info), 0.1);
  --mms-success-soft: rgba(var(--v-theme-success), 0.1);
  --mms-warning-soft: rgba(var(--v-theme-warning), 0.12);
  --mms-danger-soft: rgba(var(--v-theme-error), 0.1);
  --mms-disabled-bg: rgba(var(--v-theme-on-surface), 0.12);
  --mms-disabled-text: rgba(var(--v-theme-on-surface), 0.68);
  --mms-on-accent: rgb(var(--v-theme-on-primary));
}

.plugin-workbench {
  display: flex;
  min-height: min(780px, 92vh);
  flex-direction: column;
  overflow: hidden;
  background: var(--mms-surface);
  color: var(--mms-text);
  letter-spacing: 0;
}

.delete-dialog {
  background: var(--mms-surface);
  color: var(--mms-text);
}

.sync-console :deep(.text-medium-emphasis),
.delete-dialog :deep(.text-medium-emphasis) {
  color: var(--mms-muted) !important;
  opacity: 1 !important;
}

.sync-console :deep(.text-primary),
.delete-dialog :deep(.text-primary) {
  color: var(--mms-accent) !important;
}

.sync-console :deep(.text-secondary),
.delete-dialog :deep(.text-secondary) {
  color: var(--mms-secondary) !important;
}

.sync-console :deep(.text-success),
.delete-dialog :deep(.text-success) {
  color: var(--mms-success) !important;
}

.sync-console :deep(.text-warning),
.delete-dialog :deep(.text-warning) {
  color: var(--mms-warning) !important;
}

.sync-console :deep(.text-error),
.delete-dialog :deep(.text-error) {
  color: var(--mms-danger) !important;
}

.sync-console :deep(.text-info),
.delete-dialog :deep(.text-info) {
  color: var(--mms-info) !important;
}

.sync-console :deep(.bg-primary),
.delete-dialog :deep(.bg-primary) {
  background-color: var(--mms-accent) !important;
  color: var(--mms-on-accent) !important;
}

.sync-console :deep(.v-divider),
.delete-dialog :deep(.v-divider) {
  border-color: var(--mms-border) !important;
  opacity: 1;
}

.sync-console :deep(.v-chip.text-warning) {
  background: var(--mms-warning-soft) !important;
  color: var(--mms-warning) !important;
}

.sync-console :deep(.v-chip.text-warning .v-chip__underlay),
.delete-dialog :deep(.v-alert .v-alert__underlay) {
  opacity: 0 !important;
}

.delete-dialog :deep(.v-alert.text-warning) {
  background: var(--mms-warning-soft) !important;
  color: var(--mms-warning) !important;
}

.delete-dialog :deep(.v-alert.text-error) {
  background: var(--mms-danger-soft) !important;
  color: var(--mms-danger) !important;
}

.sync-console :deep(.v-tab) {
  color: var(--mms-muted);
  opacity: 1;
}

.sync-console :deep(.v-tab.v-tab--selected) {
  color: var(--mms-accent) !important;
}

.sync-console :deep(.v-btn--disabled),
.delete-dialog :deep(.v-btn--disabled) {
  color: var(--mms-disabled-text) !important;
  opacity: 1 !important;
}

.command-grid :deep(.v-btn--disabled),
.missing-tools :deep(.v-btn--disabled),
.dialog-actions :deep(.v-btn--disabled) {
  border-color: var(--mms-border) !important;
  background: var(--mms-disabled-bg) !important;
  box-shadow: none !important;
}

.sync-console :deep(.v-btn--disabled .v-btn__overlay),
.delete-dialog :deep(.v-btn--disabled .v-btn__overlay) {
  opacity: 0 !important;
}

.console-header,
.identity-row,
.header-meta,
.header-actions,
.section-heading,
.monitor-state,
.path-item,
.missing-tools,
.cloud-cell,
.stage-heading,
.dialog-header,
.dialog-actions,
.task-banner,
.delete-report {
  display: flex;
  align-items: center;
}

.console-header {
  justify-content: space-between;
  gap: 16px;
  padding: 16px 20px;
}

.identity-block {
  min-width: 0;
}

.identity-row {
  gap: 10px;
  min-width: 0;
}

.header-meta {
  gap: 10px;
  margin-top: 3px;
  color: var(--mms-muted);
  font-size: 0.76rem;
}

.status-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-height: 24px;
  padding: 2px 8px;
  border: 1px solid var(--mms-border);
  border-radius: 12px;
  color: var(--mms-muted);
  font-size: 0.72rem;
  white-space: nowrap;
}

.status-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: currentColor;
}

.status-pill.success { color: var(--mms-success); }
.status-pill.working { color: var(--mms-info); }
.status-pill.error { color: var(--mms-danger); }
.status-pill.muted { color: var(--mms-muted); }

.header-actions {
  flex: 0 0 auto;
  gap: 2px;
}

.header-actions :deep(.v-btn),
.command-grid :deep(.v-btn),
.missing-tools :deep(.v-btn),
.missing-row :deep(.v-btn) {
  min-width: 44px;
  min-height: 44px;
}

.initial-loading,
.inline-loading,
.empty-state {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  min-height: 220px;
  color: var(--mms-muted);
}

.task-banner,
.delete-report {
  gap: 9px;
  min-height: 40px;
  padding: 8px 20px;
  border-bottom: 1px solid var(--mms-border);
  background: var(--mms-info-soft);
  font-size: 0.82rem;
}

.task-banner.error,
.delete-report.error { background: var(--mms-danger-soft); color: var(--mms-danger); }
.delete-report.success { background: var(--mms-success-soft); color: var(--mms-success); }

.view-tabs {
  flex: 0 0 auto;
  padding: 0 8px;
}

.tab-count,
.heading-count {
  display: inline-flex;
  min-width: 20px;
  height: 20px;
  align-items: center;
  justify-content: center;
  margin-left: 7px;
  padding: 0 6px;
  border-radius: 10px;
  background: var(--mms-chip-bg);
  font-size: 0.7rem;
}

.tab-count.warning {
  background: var(--mms-warning-soft);
  color: var(--mms-warning);
}

.console-body {
  flex: 1 1 auto;
  overflow-y: auto;
}

.metric-grid,
.missing-metrics {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  border-bottom: 1px solid var(--mms-border);
}

.metric-cell {
  display: flex;
  align-items: center;
  gap: 11px;
  min-height: 74px;
  padding: 12px 18px;
}

.metric-cell + .metric-cell,
.missing-metrics > div + div {
  border-left: 1px solid var(--mms-border);
}

.metric-value,
.missing-metrics strong {
  font-size: 1.18rem;
  font-weight: 650;
  line-height: 1.2;
}

.metric-label,
.missing-metrics span,
.section-meta,
.panel-empty,
.stage-empty,
.more-files {
  color: var(--mms-muted);
  font-size: 0.75rem;
}

.command-section,
.missing-toolbar {
  padding: 18px 20px;
  border-bottom: 1px solid var(--mms-border);
}

.section-heading,
.missing-toolbar {
  justify-content: space-between;
  gap: 18px;
}

.monitor-state {
  gap: 6px;
  color: var(--mms-muted);
  font-size: 0.76rem;
}

.monitor-state.active { color: var(--mms-success); }

.command-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
  margin-top: 14px;
}

.path-section {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 24px minmax(0, 1fr);
  align-items: center;
  gap: 8px;
  padding: 14px 20px;
  border-bottom: 1px solid var(--mms-border);
  background: var(--mms-subtle);
}

.path-item {
  min-width: 0;
  gap: 8px;
}

.path-label {
  flex: 0 0 auto;
  color: var(--mms-muted);
  font-size: 0.72rem;
  font-weight: 600;
}

.path-item code,
.activity-row code,
.stage-files code {
  min-width: 0;
  overflow-wrap: anywhere;
  font-size: 0.74rem;
}

.path-arrow {
  color: var(--mms-muted);
}

.workspace-grid,
.activity-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.workspace-panel,
.activity-panel {
  min-width: 0;
  padding: 18px 20px;
}

.workspace-panel + .workspace-panel,
.activity-panel + .activity-panel {
  border-left: 1px solid var(--mms-border);
}

.panel-heading {
  display: flex;
  align-items: center;
  min-height: 28px;
  margin-bottom: 8px;
  font-size: 0.83rem;
  font-weight: 650;
}

.detail-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
  min-height: 37px;
  border-bottom: 1px solid var(--mms-border-soft);
  font-size: 0.78rem;
}

.detail-row span { color: var(--mms-muted); }
.detail-row strong { text-align: right; font-weight: 600; }

.missing-summary-copy {
  flex: 1 1 auto;
  min-width: 0;
}

.missing-tools {
  flex: 1 1 520px;
  justify-content: flex-end;
  gap: 10px;
}

.missing-search {
  max-width: 320px;
}

.missing-metrics > div {
  display: flex;
  min-height: 66px;
  align-items: baseline;
  justify-content: center;
  gap: 7px;
  padding: 15px 12px;
}

.delete-report {
  border-top: 0;
}

.delete-report > div {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 1px;
}

.delete-report strong { font-size: 0.78rem; }
.delete-report span { color: var(--mms-muted); font-size: 0.72rem; }

.missing-table {
  min-width: 0;
}

.missing-head,
.missing-row {
  display: grid;
  grid-template-columns: minmax(180px, 1.2fr) 132px minmax(190px, 1fr) 104px 42px;
  align-items: center;
  gap: 12px;
  padding: 0 20px;
}

.missing-head {
  min-height: 38px;
  border-bottom: 1px solid var(--mms-border);
  background: var(--mms-subtle);
  color: var(--mms-muted);
  font-size: 0.7rem;
  font-weight: 600;
}

.missing-row {
  min-height: 66px;
  border-bottom: 1px solid var(--mms-border-soft);
}

.missing-row:hover { background: var(--mms-hover); }

.file-cell,
.source-cell {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 2px;
}

.file-cell strong { font-size: 0.82rem; }
.file-cell span,
.source-cell span,
.source-cell small {
  overflow: hidden;
  color: var(--mms-muted);
  font-size: 0.72rem;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.missing-chip-cell {
  display: flex;
  gap: 5px;
  flex-wrap: wrap;
}

.cloud-cell {
  gap: 5px;
  font-size: 0.72rem;
}

.cloud-cell.ready { color: var(--mms-success); }
.cloud-cell.blocked { color: var(--mms-danger); }

.pagination {
  padding: 14px 8px;
}

.activity-grid {
  min-height: 540px;
}

.activity-panel .panel-heading {
  justify-content: space-between;
}

.activity-list,
.log-list {
  max-height: 560px;
  overflow-y: auto;
}

.activity-row {
  display: grid;
  grid-template-columns: 24px minmax(0, 1fr);
  gap: 8px;
  padding: 10px 0;
  border-bottom: 1px solid var(--mms-border-soft);
}

.activity-row > div {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 3px;
}

.activity-row span { color: var(--mms-muted); font-size: 0.72rem; }

.log-list {
  display: flex;
  flex-direction: column-reverse;
}

.log-list code {
  padding: 7px 0;
  border-bottom: 1px solid var(--mms-border-soft);
  overflow-wrap: anywhere;
  font-size: 0.71rem;
}

.dialog-header {
  justify-content: space-between;
  gap: 16px;
  padding: 15px 18px;
}

.dialog-content {
  max-height: min(640px, 72vh);
  overflow-y: auto;
  padding: 18px;
}

.dialog-loading { min-height: 180px; }

.delete-stage-list {
  margin: 14px 0 8px;
  border-top: 1px solid var(--mms-border);
}

.delete-stage {
  padding: 12px 0;
  border-bottom: 1px solid var(--mms-border);
}

.stage-heading {
  gap: 8px;
  font-size: 0.8rem;
}

.stage-heading span {
  margin-left: auto;
  color: var(--mms-muted);
  font-size: 0.72rem;
}

.stage-files {
  display: flex;
  flex-direction: column;
  gap: 3px;
  margin-top: 8px;
  padding-left: 28px;
}

.stage-empty { margin-top: 6px; padding-left: 28px; }

.dialog-actions {
  justify-content: flex-end;
  gap: 8px;
  padding: 12px 18px;
}

@media (max-width: 760px) {
  .sync-console {
    min-height: 100vh;
  }

  .console-header,
  .command-section,
  .missing-toolbar,
  .workspace-panel,
  .activity-panel {
    padding-right: 16px;
    padding-left: 16px;
  }

  .identity-row {
    align-items: flex-start;
    flex-direction: column;
    gap: 5px;
  }

  .header-meta span + span { display: none; }

  .metric-grid,
  .missing-metrics {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .metric-cell:nth-child(3),
  .metric-cell:nth-child(4),
  .missing-metrics > div:nth-child(3),
  .missing-metrics > div:nth-child(4) {
    border-top: 1px solid var(--mms-border);
  }

  .metric-cell:nth-child(3),
  .missing-metrics > div:nth-child(3) {
    border-left: 0;
  }

  .command-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .path-section {
    grid-template-columns: minmax(0, 1fr);
  }

  .path-arrow { display: none; }

  .workspace-grid,
  .activity-grid {
    grid-template-columns: minmax(0, 1fr);
  }

  .workspace-panel + .workspace-panel,
  .activity-panel + .activity-panel {
    border-top: 1px solid var(--mms-border);
    border-left: 0;
  }

  .missing-toolbar {
    align-items: stretch;
    flex-direction: column;
  }

  .missing-tools {
    flex: 0 0 auto;
    align-items: stretch;
    flex-direction: column;
  }

  .missing-search { max-width: none; }

  .missing-head { display: none; }

  .missing-row {
    grid-template-columns: minmax(0, 1fr) 40px;
    gap: 9px 12px;
    padding: 13px 16px;
  }

  .file-cell { grid-column: 1; }
  .missing-row > .v-btn { grid-column: 2; grid-row: 1; }
  .missing-chip-cell,
  .source-cell,
  .cloud-cell { grid-column: 1 / -1; }

  .source-cell {
    flex-direction: row;
    gap: 8px;
  }

  .activity-grid { min-height: 0; }

  .dialog-content { max-height: 68vh; }
}

@media (prefers-reduced-motion: reduce) {
  .plugin-workbench *,
  .plugin-workbench *::before,
  .plugin-workbench *::after {
    scroll-behavior: auto !important;
    transition-duration: 0.01ms !important;
    animation-duration: 0.01ms !important;
  }
}
</style>
