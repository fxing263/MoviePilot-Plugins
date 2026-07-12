<template>
  <div class="file-search-page">
    <header class="page-header">
      <div class="identity-block">
        <div class="identity-row">
          <div class="text-h6">目录文件搜索删除</div>
          <span class="status-pill" :class="statusTone">
            <span class="status-dot" />
            {{ statusLabel }}
          </span>
        </div>
        <div class="root-path">
          <v-icon icon="mdi-folder-outline" size="15" />
          <code>{{ rootPath || '未配置目录' }}</code>
        </div>
      </div>
      <div class="header-actions">
        <v-btn
          icon="mdi-refresh"
          variant="text"
          size="small"
          title="刷新"
          :loading="refreshing"
          @click="refreshAll"
        />
        <v-btn icon="mdi-cog" variant="text" size="small" title="设置" @click="emit('switch')" />
        <v-btn icon="mdi-close" variant="text" size="small" title="关闭" @click="emit('close')" />
      </div>
    </header>

    <v-divider />

    <div v-if="initialLoading" class="initial-loading">
      <v-progress-circular indeterminate color="primary" size="26" width="2" />
      <span>正在读取插件状态</span>
    </div>

    <template v-else>
      <div v-if="taskBusy || state.last_error" class="task-banner" :class="taskFailed ? 'error' : ''">
        <v-progress-circular v-if="taskBusy" indeterminate size="18" width="2" />
        <v-icon v-else icon="mdi-alert-circle-outline" size="19" />
        <span>{{ state.last_error || state.task_message }}</span>
      </div>

      <section class="search-toolbar">
        <v-text-field
          v-model="searchInput"
          class="search-input"
          label="搜索文件名或相对路径"
          prepend-inner-icon="mdi-magnify"
          variant="outlined"
          density="compact"
          clearable
          hide-details
          :disabled="!state.enabled || taskBusy"
          @keyup.enter="submitSearch"
        />
        <v-btn
          color="primary"
          prepend-icon="mdi-folder-search-outline"
          :loading="state.task_kind === 'search' && taskBusy"
          :disabled="searchDisabled"
          @click="submitSearch"
        >
          搜索
        </v-btn>
      </section>

      <section class="metric-grid" aria-label="搜索结果概览">
        <div class="metric-cell">
          <v-icon icon="mdi-file-find-outline" color="primary" size="20" />
          <div><strong>{{ searchSummary.matched_files || 0 }}</strong><span>匹配文件</span></div>
        </div>
        <div class="metric-cell">
          <v-icon icon="mdi-file-tree-outline" color="secondary" size="20" />
          <div><strong>{{ searchSummary.scanned_files || 0 }}</strong><span>已扫描文件</span></div>
        </div>
        <div class="metric-cell">
          <v-icon icon="mdi-alert-outline" :color="searchSummary.failed_entries ? 'warning' : 'success'" size="20" />
          <div><strong>{{ searchSummary.failed_entries || 0 }}</strong><span>不可访问</span></div>
        </div>
        <div class="metric-cell">
          <v-icon icon="mdi-clock-outline" color="info" size="20" />
          <div><strong class="metric-time">{{ formatShortTime(searchSummary.generated_at) || '-' }}</strong><span>完成时间</span></div>
        </div>
      </section>

      <section v-if="deleteReport" class="delete-report" :class="deleteReport.verified ? 'success' : 'error'">
        <v-icon :icon="deleteReport.verified ? 'mdi-check-circle-outline' : 'mdi-alert-circle-outline'" size="20" />
        <div>
          <strong>{{ deleteReport.message }}</strong>
          <span>{{ deleteReportDetail }}</span>
        </div>
      </section>

      <section v-if="totalResults > 0 && !resultsLoading" class="selection-toolbar">
        <div class="selection-summary">
          <v-icon icon="mdi-checkbox-multiple-marked-outline" size="19" />
          <span>已选择 <strong>{{ selectedCount }}</strong> / {{ totalResults }} 项</span>
          <v-chip v-if="allSearchResultsSelected" size="x-small" color="primary" variant="tonal">
            全部结果
          </v-chip>
        </div>
        <div class="selection-actions">
          <v-btn
            variant="text"
            size="small"
            :prepend-icon="currentPageAllSelected ? 'mdi-checkbox-multiple-blank-outline' : 'mdi-checkbox-multiple-marked-outline'"
            :disabled="taskBusy || currentPageIds.length < 1"
            @click="toggleCurrentPage(!currentPageAllSelected)"
          >
            {{ currentPageAllSelected ? '取消当前页' : '选择当前页' }}
          </v-btn>
          <v-btn
            v-if="!allSearchResultsSelected"
            variant="text"
            size="small"
            prepend-icon="mdi-select-all"
            :disabled="taskBusy"
            @click="selectEveryResult"
          >
            全选全部 {{ totalResults }} 项
          </v-btn>
          <v-btn
            v-if="selectedCount > 0"
            variant="text"
            size="small"
            prepend-icon="mdi-selection-remove"
            :disabled="taskBusy"
            @click="clearSelection"
          >
            清空
          </v-btn>
          <v-btn
            color="error"
            size="small"
            prepend-icon="mdi-delete-sweep-outline"
            :disabled="taskBusy || selectedCount < 1"
            @click="openSelectedDeletePreview"
          >
            删除所选源文件
          </v-btn>
        </div>
      </section>

      <main class="results-area">
        <div v-if="resultsLoading" class="inline-loading">
          <v-progress-circular indeterminate size="22" width="2" color="primary" />
          <span>正在读取搜索结果</span>
        </div>
        <div v-else-if="!state.enabled" class="empty-state">
          <v-icon icon="mdi-power-plug-off-outline" size="38" />
          <strong>插件未启用</strong>
        </div>
        <div v-else-if="!rootPath" class="empty-state">
          <v-icon icon="mdi-folder-alert-outline" size="38" color="warning" />
          <strong>尚未配置搜索目录</strong>
        </div>
        <div v-else-if="!results.length" class="empty-state">
          <v-icon :icon="hasSearched ? 'mdi-file-search-outline' : 'mdi-magnify'" size="38" />
          <strong>{{ hasSearched ? '没有匹配文件' : '等待搜索' }}</strong>
        </div>
        <div v-else class="results-table">
          <div class="results-head">
            <v-checkbox-btn
              class="selection-checkbox"
              :model-value="currentPageAllSelected"
              :indeterminate="currentPagePartiallySelected"
              density="compact"
              title="选择当前页"
              @update:model-value="toggleCurrentPage"
            />
            <span>文件</span>
            <span>相对路径</span>
            <span>大小</span>
            <span>修改时间</span>
            <span />
          </div>
          <div v-for="item in results" :key="item.item_id" class="result-row">
            <v-checkbox-btn
              class="selection-checkbox"
              :model-value="isItemSelected(item.item_id)"
              density="compact"
              :title="`选择 ${item.name}`"
              @update:model-value="toggleItemSelection(item.item_id, $event)"
            />
            <div class="file-cell">
              <v-icon :icon="fileIcon(item)" color="primary" size="21" />
              <div>
                <strong>{{ item.name }}</strong>
                <span>{{ item.suffix || '无扩展名' }}</span>
              </div>
            </div>
            <code class="path-cell" :title="item.absolute_path">{{ item.relative_path }}</code>
            <span class="size-cell">{{ formatBytes(item.size) }}</span>
            <span class="time-cell">{{ formatTime(item.modified_at) }}</span>
            <v-btn
              icon="mdi-delete-outline"
              color="error"
              variant="text"
              size="small"
              title="永久删除源文件"
              :disabled="taskBusy"
              @click="openDeletePreview(item)"
            />
          </div>
        </div>

        <v-pagination
          v-if="pageCount > 1"
          v-model="currentPage"
          :length="pageCount"
          density="comfortable"
          class="pagination"
          @update:model-value="() => loadResults()"
        />
      </main>

      <footer class="activity-footer">
        <div>
          <span>最近搜索</span>
          <strong>{{ searchSummary.query || '-' }}</strong>
        </div>
        <div>
          <span>结果状态</span>
          <strong>{{ searchSummary.message || '尚未搜索' }}</strong>
        </div>
      </footer>
    </template>

    <v-dialog v-model="deleteDialog.show" max-width="680" persistent>
        <v-card class="delete-dialog">
          <v-card-title class="dialog-header">
            <div>
              <div class="text-subtitle-1 font-weight-medium">永久删除源文件</div>
              <div class="dialog-subtitle">{{ deleteDialogSubtitle }}</div>
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
            <span>正在生成删除预览</span>
          </div>
          <template v-else-if="deleteDialog.plan">
            <v-alert
              v-if="deleteDialog.plan.blocked_reasons?.length"
              type="error"
              variant="tonal"
              density="compact"
            >
              {{ deleteDialog.plan.blocked_reasons.join('；') }}
            </v-alert>
            <v-alert v-else type="warning" variant="tonal" density="compact">
              将永久删除配置目录中的真实文件，无法撤销。执行前会再次校验整批文件快照。
            </v-alert>

            <div class="preview-list">
              <div><span>源文件数量</span><strong>{{ deleteDialog.plan.selected_count }}</strong></div>
              <div><span>文件总大小</span><strong>{{ formatBytes(deleteDialog.plan.total_size) }}</strong></div>
              <div><span>可执行数量</span><strong>{{ deleteDialog.plan.ready_count }}</strong></div>
            </div>

            <div class="batch-preview-list">
              <div v-for="item in deleteDialog.plan.items?.slice(0, 12)" :key="item.item_id">
                <code>{{ item.relative_path }}</code>
                <span>{{ formatBytes(item.size) }}</span>
              </div>
              <div v-if="deleteDialog.plan.preview_truncated" class="preview-more">
                其余文件已绑定到本次确认令牌
              </div>
            </div>

            <v-checkbox
              v-model="deleteDialog.confirmed"
              color="error"
              hide-details
              :label="`我确认永久删除以上 ${deleteDialog.plan.selected_count} 个源文件`"
              :disabled="deleteDialog.plan.blocked_reasons?.length > 0"
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
            @click="submitDelete"
          >
            永久删除
          </v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <v-snackbar v-model="snackbar.show" :color="snackbar.color" timeout="4200">
      {{ snackbar.text }}
    </v-snackbar>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'

import { DIRECTORY_FILE_SEARCH_PLUGIN_ID } from '../utils/pluginId.js'

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
const pluginId = DIRECTORY_FILE_SEARCH_PLUGIN_ID
const initialLoading = ref(true)
const refreshing = ref(false)
const resultsLoading = ref(false)
const searchInput = ref('')
const results = ref([])
const currentPage = ref(1)
const pageCount = ref(1)
const totalResults = ref(0)
const selectedItemIds = ref([])
const excludedItemIds = ref([])
const allSearchResultsSelected = ref(false)
const snackbar = reactive({ show: false, text: '', color: 'info' })
const state = reactive(createInitialState())
const deleteDialog = reactive({
  show: false,
  loading: false,
  submitting: false,
  confirmed: false,
  selection: null,
  plan: null,
})
let pollTimer = null
let lastObservedTask = ''

function createInitialState() {
  return {
    enabled: false,
    task_status: 'idle',
    task_kind: '',
    task_message: '',
    task_started_at: '',
    task_finished_at: '',
    last_error: '',
    search: {},
    last_report: {},
    logs: [],
    config: { root_dir: '' },
  }
}

const busyStatuses = new Set(['queued', 'pending', 'running', 'searching', 'deleting', 'working', 'in_progress'])
const failedStatuses = new Set(['failed', 'error'])
const taskStatus = computed(() => String(state.task_status || 'idle').toLowerCase())
const taskBusy = computed(() => busyStatuses.has(taskStatus.value))
const taskFailed = computed(() => failedStatuses.has(taskStatus.value))
const rootPath = computed(() => state.config?.root_dir || props.initialConfig.root_dir || '')
const searchSummary = computed(() => state.search || {})
const hasSearched = computed(() => Boolean(searchSummary.value.generated_at || searchSummary.value.query))
const deleteReport = computed(() => (
  ['delete', 'delete_batch'].includes(state.last_report?.kind)
    ? state.last_report
    : null
))
const deleteReportDetail = computed(() => {
  if (!deleteReport.value) return ''
  if (deleteReport.value.kind === 'delete_batch') {
    return `复核通过 ${deleteReport.value.verified_count || 0} / ${deleteReport.value.requested_count || 0} 项`
  }
  return deleteReport.value.result?.relative_path || ''
})
const selectedCount = computed(() => (
  allSearchResultsSelected.value
    ? Math.max(0, totalResults.value - excludedItemIds.value.length)
    : selectedItemIds.value.length
))
const currentPageIds = computed(() => results.value.map((item) => item.item_id))
const currentPageSelectedCount = computed(() => currentPageIds.value.filter(
  (itemId) => isItemSelected(itemId),
).length)
const currentPageAllSelected = computed(() => (
  currentPageIds.value.length > 0
  && currentPageSelectedCount.value === currentPageIds.value.length
))
const currentPagePartiallySelected = computed(() => (
  currentPageSelectedCount.value > 0
  && !currentPageAllSelected.value
))
const deleteDialogSubtitle = computed(() => {
  const count = Number(deleteDialog.plan?.selected_count || 0)
  if (count > 1) return `已选择 ${count} 个源文件`
  return deleteDialog.plan?.items?.[0]?.relative_path || '正在核对删除目标'
})
const searchDisabled = computed(() => (
  !state.enabled
  || !rootPath.value
  || taskBusy.value
  || !String(searchInput.value || '').trim()
))
const deleteReady = computed(() => Boolean(
  deleteDialog.plan
  && !deleteDialog.loading
  && !deleteDialog.submitting
  && deleteDialog.confirmed
  && deleteDialog.plan.confirm_token
  && !deleteDialog.plan.blocked_reasons?.length
))
const statusTone = computed(() => {
  if (!state.enabled) return 'muted'
  if (taskFailed.value) return 'error'
  if (taskBusy.value) return 'working'
  return 'success'
})
const statusLabel = computed(() => {
  if (!state.enabled) return '未启用'
  if (taskFailed.value) return '任务失败'
  if (taskBusy.value) return '任务执行中'
  return '空闲'
})

const normalizeSuccess = (result) => {
  if (!result || typeof result !== 'object') return false
  if (typeof result.success === 'boolean') return result.success
  if (Object.prototype.hasOwnProperty.call(result, 'code')) return Number(result.code) === 0
  return true
}

const resultMessage = (result, fallback = '') => result?.message || result?.msg || fallback

const request = async (method, url, data = undefined) => {
  if (typeof props.api === 'function') {
    return props.api({ method: method.toUpperCase(), url, data })
  }
  const handler = props.api?.[method]
  if (typeof handler !== 'function') throw new Error('页面 API 未就绪')
  return handler.call(props.api, url, data)
}

const showMessage = (text, color = 'info') => {
  snackbar.text = text
  snackbar.color = color
  snackbar.show = true
}

const schedulePoll = (delay) => {
  if (pollTimer) window.clearTimeout(pollTimer)
  pollTimer = window.setTimeout(() => loadState({ silent: true }), delay)
}

const loadState = async ({ silent = false } = {}) => {
  if (!silent) refreshing.value = true
  try {
    const result = await request('get', `plugin/${pluginId}/status`)
    if (!normalizeSuccess(result)) throw new Error(resultMessage(result, '读取插件状态失败'))
    const previousBusy = taskBusy.value
    Object.assign(state, createInitialState(), result.data || {})
    state.search = state.search && typeof state.search === 'object' ? state.search : {}
    state.last_report = state.last_report && typeof state.last_report === 'object' ? state.last_report : {}
    if (!searchInput.value && state.search.query) searchInput.value = state.search.query
    const taskKey = `${state.task_kind}:${state.task_status}:${state.task_finished_at}`
    if (previousBusy && !taskBusy.value && taskKey !== lastObservedTask) {
      lastObservedTask = taskKey
      await loadResults({ silent: true })
      showMessage(state.task_message || '后台任务已结束', taskFailed.value ? 'error' : 'success')
    }
  } catch (error) {
    showMessage(error?.message || '读取插件状态失败', 'error')
  } finally {
    initialLoading.value = false
    if (!silent) refreshing.value = false
    schedulePoll(taskBusy.value ? 900 : 5000)
  }
}

const loadResults = async ({ silent = false } = {}) => {
  if (!silent) resultsLoading.value = true
  try {
    const query = new URLSearchParams({
      page: String(currentPage.value),
      page_size: '50',
    })
    const result = await request('get', `plugin/${pluginId}/results?${query.toString()}`)
    if (!normalizeSuccess(result)) throw new Error(resultMessage(result, '读取搜索结果失败'))
    const data = result.data || {}
    results.value = Array.isArray(data.items) ? data.items : []
    totalResults.value = Number(data.total || 0)
    currentPage.value = Number(data.page || 1)
    pageCount.value = Number(data.page_count || 1)
    if (data.summary && typeof data.summary === 'object') state.search = data.summary
  } catch (error) {
    showMessage(error?.message || '读取搜索结果失败', 'error')
  } finally {
    if (!silent) resultsLoading.value = false
  }
}

const refreshAll = async () => {
  await loadState()
  await loadResults()
}

const submitSearch = async () => {
  if (searchDisabled.value) return
  const keyword = String(searchInput.value || '').trim()
  try {
    const query = new URLSearchParams({ query: keyword })
    const result = await request('post', `plugin/${pluginId}/search?${query.toString()}`)
    if (!normalizeSuccess(result)) throw new Error(resultMessage(result, '搜索任务提交失败'))
    currentPage.value = 1
    results.value = []
    totalResults.value = 0
    clearSelection()
    state.task_status = result.data?.status || 'queued'
    state.task_kind = 'search'
    state.task_message = resultMessage(result, '搜索任务已提交')
    state.search = { query: keyword, message: '搜索任务已提交' }
    showMessage(state.task_message, 'info')
    emit('action', { action: 'search', response: result })
    schedulePoll(450)
  } catch (error) {
    showMessage(error?.message || '搜索任务提交失败', 'error')
  }
}

const isItemSelected = (itemId) => (
  allSearchResultsSelected.value
    ? !excludedItemIds.value.includes(itemId)
    : selectedItemIds.value.includes(itemId)
)

const toggleItemSelection = (itemId, selected) => {
  if (allSearchResultsSelected.value) {
    excludedItemIds.value = selected
      ? excludedItemIds.value.filter((candidate) => candidate !== itemId)
      : [...new Set([...excludedItemIds.value, itemId])]
    return
  }
  selectedItemIds.value = selected
    ? [...new Set([...selectedItemIds.value, itemId])]
    : selectedItemIds.value.filter((candidate) => candidate !== itemId)
}

const toggleCurrentPage = (selected) => {
  const pageIds = currentPageIds.value
  if (allSearchResultsSelected.value) {
    const pageIdSet = new Set(pageIds)
    excludedItemIds.value = selected
      ? excludedItemIds.value.filter((itemId) => !pageIdSet.has(itemId))
      : [...new Set([...excludedItemIds.value, ...pageIds])]
    return
  }
  const pageIdSet = new Set(pageIds)
  selectedItemIds.value = selected
    ? [...new Set([...selectedItemIds.value, ...pageIds])]
    : selectedItemIds.value.filter((itemId) => !pageIdSet.has(itemId))
}

const selectEveryResult = () => {
  allSearchResultsSelected.value = true
  selectedItemIds.value = []
  excludedItemIds.value = []
}

const clearSelection = () => {
  allSearchResultsSelected.value = false
  selectedItemIds.value = []
  excludedItemIds.value = []
}

const selectedDeletePayload = () => ({
  select_all: allSearchResultsSelected.value,
  item_ids: allSearchResultsSelected.value ? [] : [...selectedItemIds.value],
  excluded_item_ids: allSearchResultsSelected.value ? [...excludedItemIds.value] : [],
})

const openSelectionDeletePreview = async (selection) => {
  Object.assign(deleteDialog, {
    show: true,
    loading: true,
    submitting: false,
    confirmed: false,
    selection,
    plan: null,
  })
  try {
    const result = await request(
      'post',
      `plugin/${pluginId}/delete-batch-preview`,
      selection,
    )
    if (!normalizeSuccess(result)) throw new Error(resultMessage(result, '生成源文件删除预览失败'))
    deleteDialog.plan = result.data || null
  } catch (error) {
    showMessage(error?.message || '生成源文件删除预览失败', 'error')
    deleteDialog.show = false
  } finally {
    deleteDialog.loading = false
  }
}

const openDeletePreview = async (item) => {
  await openSelectionDeletePreview({
    select_all: false,
    item_ids: [item.item_id],
    excluded_item_ids: [],
  })
}

const openSelectedDeletePreview = async () => {
  if (selectedCount.value < 1) return
  await openSelectionDeletePreview(selectedDeletePayload())
}

const closeDeleteDialog = () => {
  if (deleteDialog.submitting) return
  deleteDialog.show = false
}

const submitDelete = async () => {
  if (!deleteReady.value) return
  deleteDialog.submitting = true
  try {
    const payload = {
      confirmed: true,
      confirm_token: deleteDialog.plan.confirm_token,
    }
    const result = await request('post', `plugin/${pluginId}/delete-batch`, payload)
    if (!normalizeSuccess(result)) throw new Error(resultMessage(result, '删除任务提交失败'))
    state.task_status = result.data?.status || 'queued'
    state.task_kind = 'delete_batch'
    state.task_message = resultMessage(result, '删除任务已提交')
    deleteDialog.show = false
    clearSelection()
    showMessage(state.task_message, 'info')
    emit('action', { action: 'delete_batch', response: result })
    schedulePoll(450)
  } catch (error) {
    showMessage(error?.message || '删除任务提交失败', 'error')
  } finally {
    deleteDialog.submitting = false
  }
}

const formatBytes = (value) => {
  const bytes = Number(value || 0)
  if (!Number.isFinite(bytes) || bytes <= 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  const unitIndex = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1)
  const amount = bytes / (1024 ** unitIndex)
  return `${amount >= 10 || unitIndex === 0 ? amount.toFixed(0) : amount.toFixed(1)} ${units[unitIndex]}`
}

const formatTime = (value) => {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value).replace('T', ' ')
  return date.toLocaleString('zh-CN', { hour12: false })
}

const formatShortTime = (value) => {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  return date.toLocaleTimeString('zh-CN', { hour12: false })
}

const fileIcon = (item) => {
  const suffix = String(item.suffix || '').toLowerCase()
  if (['.jpg', '.jpeg', '.png', '.webp', '.gif'].includes(suffix)) return 'mdi-file-image-outline'
  if (['.mp4', '.mkv', '.avi', '.mov', '.strm'].includes(suffix)) return 'mdi-file-video-outline'
  if (['.json', '.xml', '.yaml', '.yml'].includes(suffix)) return 'mdi-code-json'
  if (['.zip', '.rar', '.7z', '.tar', '.gz'].includes(suffix)) return 'mdi-folder-zip-outline'
  return 'mdi-file-outline'
}

onMounted(async () => {
  await loadState()
  await loadResults({ silent: true })
})

onBeforeUnmount(() => {
  if (pollTimer) window.clearTimeout(pollTimer)
})
</script>

<style scoped>
.file-search-page,
.delete-dialog {
  --dfs-surface: #ffffff;
  --dfs-subtle: #f3f4f6;
  --dfs-hover: #f8fafc;
  --dfs-text: #1f2937;
  --dfs-muted: #4b5563;
  --dfs-border: #d1d5db;
  --dfs-border-soft: #e5e7eb;
  --dfs-accent: #2563eb;
  --dfs-secondary: #0f766e;
  --dfs-success: #15803d;
  --dfs-warning: #a16207;
  --dfs-danger: #b91c1c;
  --dfs-info: #0369a1;
  --dfs-success-soft: #f0fdf4;
  --dfs-warning-soft: #fffbeb;
  --dfs-danger-soft: #fef2f2;
  --dfs-info-soft: #e0f2fe;
  --dfs-disabled-bg: #e5e7eb;
  --dfs-disabled-text: #374151;
  --dfs-on-accent: #ffffff;
  --v-theme-surface: 255, 255, 255;
  --v-theme-on-surface: 31, 41, 55;
  --v-theme-on-surface-variant: 75, 85, 99;
  --v-theme-primary: 37, 99, 235;
  --v-theme-on-primary: 255, 255, 255;
  --v-theme-secondary: 15, 118, 110;
  --v-theme-on-secondary: 255, 255, 255;
  --v-theme-success: 21, 128, 61;
  --v-theme-on-success: 255, 255, 255;
  --v-theme-warning: 161, 98, 7;
  --v-theme-on-warning: 255, 255, 255;
  --v-theme-error: 185, 28, 28;
  --v-theme-on-error: 255, 255, 255;
  --v-theme-info: 3, 105, 161;
  --v-theme-on-info: 255, 255, 255;
  --v-border-color: 107, 114, 128;
  --v-border-opacity: 0.38;
  --v-high-emphasis-opacity: 1;
  --v-medium-emphasis-opacity: 1;
  --v-disabled-opacity: 1;
  color-scheme: light;
}

:global(.v-theme--dark .file-search-page),
:global(.v-theme--dark .delete-dialog),
:global(.file-search-page.v-theme--dark),
:global(.delete-dialog.v-theme--dark) {
  --dfs-surface: #111827;
  --dfs-subtle: #1f2937;
  --dfs-hover: #1b2535;
  --dfs-text: #f3f4f6;
  --dfs-muted: #cbd5e1;
  --dfs-border: #475569;
  --dfs-border-soft: #334155;
  --dfs-accent: #60a5fa;
  --dfs-secondary: #5eead4;
  --dfs-success: #4ade80;
  --dfs-warning: #fbbf24;
  --dfs-danger: #f87171;
  --dfs-info: #38bdf8;
  --dfs-success-soft: #052e16;
  --dfs-warning-soft: #422006;
  --dfs-danger-soft: #450a0a;
  --dfs-info-soft: #082f49;
  --dfs-disabled-bg: #273449;
  --dfs-disabled-text: #cbd5e1;
  --dfs-on-accent: #0f172a;
  --v-theme-surface: 17, 24, 39;
  --v-theme-on-surface: 243, 244, 246;
  --v-theme-on-surface-variant: 203, 213, 225;
  --v-theme-primary: 96, 165, 250;
  --v-theme-on-primary: 15, 23, 42;
  --v-theme-secondary: 94, 234, 212;
  --v-theme-on-secondary: 15, 23, 42;
  --v-theme-success: 74, 222, 128;
  --v-theme-on-success: 15, 23, 42;
  --v-theme-warning: 251, 191, 36;
  --v-theme-on-warning: 15, 23, 42;
  --v-theme-error: 248, 113, 113;
  --v-theme-on-error: 15, 23, 42;
  --v-theme-info: 56, 189, 248;
  --v-theme-on-info: 15, 23, 42;
  --v-border-color: 148, 163, 184;
  --v-border-opacity: 0.38;
  color-scheme: dark;
}

.file-search-page {
  display: flex;
  min-height: min(720px, 90vh);
  flex-direction: column;
  overflow: hidden;
  background: var(--dfs-surface);
  color: var(--dfs-text);
  letter-spacing: 0;
}

.delete-dialog {
  background: var(--dfs-surface);
  color: var(--dfs-text);
}

.file-search-page :deep(.text-primary),
.delete-dialog :deep(.text-primary) { color: var(--dfs-accent) !important; }
.file-search-page :deep(.text-secondary),
.delete-dialog :deep(.text-secondary) { color: var(--dfs-secondary) !important; }
.file-search-page :deep(.text-success),
.delete-dialog :deep(.text-success) { color: var(--dfs-success) !important; }
.file-search-page :deep(.text-warning),
.delete-dialog :deep(.text-warning) { color: var(--dfs-warning) !important; }
.file-search-page :deep(.text-error),
.delete-dialog :deep(.text-error) { color: var(--dfs-danger) !important; }
.file-search-page :deep(.text-info),
.delete-dialog :deep(.text-info) { color: var(--dfs-info) !important; }

.file-search-page :deep(.bg-primary),
.delete-dialog :deep(.bg-primary) {
  background: var(--dfs-accent) !important;
  color: var(--dfs-on-accent) !important;
}

.file-search-page :deep(.v-divider),
.delete-dialog :deep(.v-divider) {
  border-color: var(--dfs-border) !important;
  opacity: 1;
}

.file-search-page :deep(.v-field__outline) {
  color: var(--dfs-border);
  opacity: 1;
}

.file-search-page :deep(.v-label),
.file-search-page :deep(.text-medium-emphasis),
.delete-dialog :deep(.text-medium-emphasis) {
  color: var(--dfs-muted) !important;
  opacity: 1 !important;
}

.file-search-page :deep(.v-btn--disabled),
.delete-dialog :deep(.v-btn--disabled) {
  color: var(--dfs-disabled-text) !important;
  opacity: 1 !important;
}

.search-toolbar :deep(.v-btn--disabled),
.dialog-actions :deep(.v-btn--disabled) {
  border-color: var(--dfs-border) !important;
  background: var(--dfs-disabled-bg) !important;
  box-shadow: none !important;
}

.file-search-page :deep(.v-btn--disabled .v-btn__overlay),
.delete-dialog :deep(.v-btn--disabled .v-btn__overlay),
.delete-dialog :deep(.v-alert .v-alert__underlay) {
  opacity: 0 !important;
}

.delete-dialog :deep(.v-alert.text-warning) {
  background: var(--dfs-warning-soft) !important;
  color: var(--dfs-warning) !important;
}

.delete-dialog :deep(.v-alert.text-error) {
  background: var(--dfs-danger-soft) !important;
  color: var(--dfs-danger) !important;
}

.page-header,
.identity-row,
.root-path,
.header-actions,
.search-toolbar,
.selection-toolbar,
.selection-summary,
.selection-actions,
.metric-cell,
.task-banner,
.delete-report,
.dialog-header,
.dialog-actions {
  display: flex;
  align-items: center;
}

.page-header {
  justify-content: space-between;
  gap: 16px;
  padding: 16px 20px;
}

.identity-block {
  min-width: 0;
}

.identity-row {
  gap: 10px;
}

.root-path {
  min-width: 0;
  gap: 5px;
  margin-top: 3px;
  color: var(--dfs-muted);
  font-size: 0.74rem;
}

.root-path code {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.status-pill {
  display: inline-flex;
  min-height: 24px;
  align-items: center;
  gap: 6px;
  padding: 2px 8px;
  border: 1px solid var(--dfs-border);
  border-radius: 12px;
  color: var(--dfs-muted);
  font-size: 0.72rem;
  white-space: nowrap;
}

.status-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: currentColor;
}

.status-pill.success { color: var(--dfs-success); }
.status-pill.working { color: var(--dfs-info); }
.status-pill.error { color: var(--dfs-danger); }

.header-actions {
  flex: 0 0 auto;
  gap: 2px;
}

.initial-loading,
.inline-loading,
.empty-state {
  display: flex;
  min-height: 220px;
  align-items: center;
  justify-content: center;
  gap: 10px;
  color: var(--dfs-muted);
}

.task-banner,
.delete-report {
  gap: 9px;
  min-height: 40px;
  padding: 8px 20px;
  border-bottom: 1px solid var(--dfs-border);
  background: var(--dfs-info-soft);
  color: var(--dfs-info);
  font-size: 0.8rem;
}

.task-banner.error,
.delete-report.error {
  background: var(--dfs-danger-soft);
  color: var(--dfs-danger);
}

.delete-report.success {
  background: var(--dfs-success-soft);
  color: var(--dfs-success);
}

.delete-report > div {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 1px;
}

.delete-report span {
  overflow: hidden;
  color: var(--dfs-muted);
  font-size: 0.72rem;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.search-toolbar {
  gap: 10px;
  padding: 18px 20px;
  border-bottom: 1px solid var(--dfs-border);
}

.search-input {
  min-width: 0;
  flex: 1 1 auto;
}

.search-toolbar .v-btn {
  min-width: 112px;
}

.selection-toolbar {
  min-height: 52px;
  justify-content: space-between;
  gap: 12px;
  padding: 8px 20px;
  border-bottom: 1px solid var(--dfs-border);
  background: var(--dfs-subtle);
}

.selection-summary,
.selection-actions {
  min-width: 0;
  gap: 8px;
}

.selection-summary {
  color: var(--dfs-muted);
  font-size: 0.78rem;
  white-space: nowrap;
}

.selection-summary strong {
  color: var(--dfs-text);
}

.selection-actions {
  justify-content: flex-end;
  flex-wrap: wrap;
}

.metric-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  border-bottom: 1px solid var(--dfs-border);
}

.metric-cell {
  min-height: 70px;
  gap: 10px;
  padding: 12px 18px;
}

.metric-cell + .metric-cell {
  border-left: 1px solid var(--dfs-border);
}

.metric-cell > div {
  display: flex;
  min-width: 0;
  flex-direction: column;
}

.metric-cell strong {
  font-size: 1.12rem;
  line-height: 1.25;
}

.metric-cell span {
  color: var(--dfs-muted);
  font-size: 0.72rem;
}

.metric-time {
  overflow: hidden;
  font-size: 0.86rem !important;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.results-area {
  min-height: 360px;
  flex: 1 1 auto;
  overflow-y: auto;
}

.results-table {
  min-width: 0;
}

.results-head,
.result-row {
  display: grid;
  grid-template-columns: 36px minmax(190px, 1fr) minmax(220px, 1.25fr) 86px 150px 42px;
  align-items: center;
  gap: 12px;
  padding: 0 20px;
}

.results-head {
  min-height: 38px;
  border-bottom: 1px solid var(--dfs-border);
  background: var(--dfs-subtle);
  color: var(--dfs-muted);
  font-size: 0.7rem;
  font-weight: 650;
}

.result-row {
  min-height: 64px;
  border-bottom: 1px solid var(--dfs-border-soft);
}

.result-row:hover {
  background: var(--dfs-hover);
}

.file-cell {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 9px;
}

.file-cell > div {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 2px;
}

.file-cell strong,
.file-cell span,
.path-cell,
.time-cell {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.file-cell strong {
  font-size: 0.8rem;
}

.file-cell span,
.size-cell,
.time-cell {
  color: var(--dfs-muted);
  font-size: 0.72rem;
}

.path-cell {
  color: var(--dfs-text);
  font-size: 0.73rem;
}

.pagination {
  padding: 13px 8px;
}

.activity-footer {
  display: grid;
  grid-template-columns: minmax(180px, 0.6fr) minmax(0, 1.4fr);
  gap: 18px;
  padding: 11px 20px;
  border-top: 1px solid var(--dfs-border);
  background: var(--dfs-subtle);
}

.activity-footer > div {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 8px;
}

.activity-footer span {
  flex: 0 0 auto;
  color: var(--dfs-muted);
  font-size: 0.7rem;
}

.activity-footer strong {
  overflow: hidden;
  font-size: 0.73rem;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.dialog-header {
  justify-content: space-between;
  gap: 16px;
  padding: 15px 18px;
}

.dialog-subtitle {
  margin-top: 2px;
  color: var(--dfs-muted);
  font-size: 0.74rem;
}

.dialog-content {
  max-height: min(560px, 68vh);
  overflow-y: auto;
  padding: 18px;
}

.dialog-loading {
  min-height: 170px;
}

.preview-list {
  margin: 14px 0 8px;
  border-top: 1px solid var(--dfs-border);
}

.preview-list > div {
  display: grid;
  grid-template-columns: 86px minmax(0, 1fr);
  gap: 12px;
  align-items: start;
  padding: 11px 0;
  border-bottom: 1px solid var(--dfs-border-soft);
  font-size: 0.78rem;
}

.preview-list span {
  color: var(--dfs-muted);
}

.preview-list code {
  overflow-wrap: anywhere;
}

.batch-preview-list {
  max-height: 250px;
  margin: 12px 0;
  overflow-y: auto;
  border: 1px solid var(--dfs-border);
  border-radius: 6px;
}

.batch-preview-list > div {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding: 9px 11px;
  border-bottom: 1px solid var(--dfs-border-soft);
  font-size: 0.74rem;
}

.batch-preview-list > div:last-child {
  border-bottom: 0;
}

.batch-preview-list code {
  min-width: 0;
  overflow-wrap: anywhere;
}

.batch-preview-list span,
.preview-more {
  flex: 0 0 auto;
  color: var(--dfs-muted);
}

.dialog-actions {
  justify-content: flex-end;
  gap: 8px;
  padding: 12px 18px;
}

@media (max-width: 760px) {
  .file-search-page {
    min-height: 100vh;
  }

  .page-header,
  .search-toolbar,
  .selection-toolbar {
    padding-right: 16px;
    padding-left: 16px;
  }

  .identity-row {
    align-items: flex-start;
    flex-direction: column;
    gap: 5px;
  }

  .search-toolbar {
    align-items: stretch;
    flex-direction: column;
  }

  .search-toolbar .v-btn {
    width: 100%;
  }

  .selection-toolbar {
    align-items: stretch;
    flex-direction: column;
  }

  .selection-actions {
    justify-content: stretch;
  }

  .selection-actions .v-btn:last-child {
    flex: 1 1 100%;
  }

  .metric-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .metric-cell:nth-child(3),
  .metric-cell:nth-child(4) {
    border-top: 1px solid var(--dfs-border);
  }

  .metric-cell:nth-child(3) {
    border-left: 0;
  }

  .results-head {
    display: none;
  }

  .result-row {
    grid-template-columns: 36px minmax(0, 1fr) 40px;
    gap: 8px 12px;
    padding: 13px 16px;
  }

  .result-row > .selection-checkbox { grid-column: 1; grid-row: 1; }
  .file-cell { grid-column: 2; }
  .result-row > .v-btn { grid-column: 3; grid-row: 1; }
  .path-cell,
  .size-cell,
  .time-cell { grid-column: 2 / -1; }

  .path-cell {
    white-space: normal;
    overflow-wrap: anywhere;
  }

  .size-cell::before { content: '大小  '; }
  .time-cell::before { content: '修改  '; }

  .activity-footer {
    grid-template-columns: minmax(0, 1fr);
    gap: 6px;
    padding-right: 16px;
    padding-left: 16px;
  }

  .preview-list > div {
    grid-template-columns: minmax(0, 1fr);
    gap: 4px;
  }
}
</style>
