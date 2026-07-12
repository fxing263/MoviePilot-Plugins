<template>
  <div class="plugin-workbench organizer-page">
    <header class="page-header">
      <div class="title-block">
        <div class="text-h6">Emby媒体库整理</div>
        <div class="status-line">
          <span class="status-dot" :class="statusTone" />
          <span>{{ statusText }}</span>
          <span v-if="state.scan_started_at" class="text-medium-emphasis">{{ formatTime(state.scan_started_at) }}</span>
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
          @click="loadState"
        />
        <v-btn icon="mdi-cog" variant="text" size="small" title="设置" aria-label="打开插件设置" @click="emit('switch')" />
        <v-btn icon="mdi-close" variant="text" size="small" title="关闭" aria-label="关闭插件页面" @click="emit('close')" />
      </div>
    </header>

    <v-divider />

    <div v-if="initialLoading" class="initial-loading">
      <v-progress-circular indeterminate color="primary" />
      <span>正在读取整理结果</span>
    </div>

    <template v-else>
      <div class="task-strip" :class="statusTone" aria-live="polite" aria-atomic="true">
        <v-progress-circular v-if="scanRunning" indeterminate size="18" width="2" />
        <v-icon
          v-else
          :icon="state.status === 'failed' ? 'mdi-alert-circle-outline' : 'mdi-information-outline'"
          size="20"
        />
        <span>{{ state.last_error || state.task_message || statusText }}</span>
      </div>

      <section class="metric-grid" aria-label="媒体库整理概览">
        <div class="metric-cell"><strong>{{ state.missing.total }}</strong><span>缺失元数据</span></div>
        <div class="metric-cell"><strong>{{ state.orphan.total }}</strong><span>多余元数据</span></div>
        <div class="metric-cell"><strong>{{ state.categories.length }}</strong><span>可用分类</span></div>
        <div class="metric-cell"><strong>{{ formatShortTime(state.scan_finished_at) || '-' }}</strong><span>完成时间</span></div>
      </section>

      <v-tabs v-model="activeTab" class="result-tabs" color="primary">
        <v-tab value="missing">缺失元数据 <span class="tab-count">{{ state.missing.total }}</span></v-tab>
        <v-tab value="orphan">多余元数据 <span class="tab-count">{{ state.orphan.total }}</span></v-tab>
      </v-tabs>

      <v-divider />

      <v-window v-model="activeTab" class="result-window">
        <v-window-item value="missing">
          <div class="scan-row">
            <div class="scan-copy">
              <div class="text-subtitle-2">缺失元数据扫描范围</div>
              <v-select
                :model-value="missingCategorySelection"
                :items="state.categories"
                item-title="title"
                item-value="value"
                label="选择二级分类"
                variant="outlined"
                density="compact"
                multiple
                chips
                closable-chips
                hide-details
                class="scan-select"
                @update:model-value="updateCategorySelection('missing', $event)"
              />
            </div>
            <v-btn
              color="primary"
              prepend-icon="mdi-database-search-outline"
              :loading="scanRunning && state.scan_kind === 'missing'"
              :disabled="scanRunning || !missingCategorySelection.length"
              @click="startScan('missing')"
            >
              查询缺失元数据
            </v-btn>
          </div>
          <div v-if="!state.missing.items.length" class="empty-state">
            <v-icon icon="mdi-file-check-outline" size="34" />
            <span>暂无缺失元数据结果</span>
          </div>
          <v-expansion-panels v-else v-model="expandedMissingGroup" variant="accordion" class="result-panels">
            <v-expansion-panel v-for="group in state.missing.items" :key="`${group.category}-${group.title}`">
              <v-expansion-panel-title>
                <div class="group-title">
                  <span class="text-body-1 font-weight-medium">{{ group.title }}</span>
                  <span class="text-caption text-medium-emphasis">{{ group.category }} · {{ group.items.length }}项</span>
                </div>
              </v-expansion-panel-title>
              <v-expansion-panel-text>
                <div class="episode-list">
                  <div v-for="item in group.items" :key="item.path" class="episode-row">
                    <div class="episode-main">
                      <span v-if="item.season !== '-'" class="season-label">{{ item.season }}</span>
                      <span class="episode-name">{{ item.name }}</span>
                      <div class="missing-types">
                        <v-chip v-for="type in item.missing" :key="type" size="x-small" color="warning" variant="tonal">
                          {{ type }}
                        </v-chip>
                      </div>
                    </div>
                    <div class="episode-actions">
                      <v-btn
                        color="warning"
                        variant="outlined"
                        size="small"
                        prepend-icon="mdi-delete-sweep-outline"
                        title="删除当前STRM和现有联动元数据"
                        :loading="deletingAction === `${item.path}:local`"
                        :disabled="!!deletingAction"
                        @click="executeMissingDelete(item, 'local')"
                      >
                        本地+联动
                      </v-btn>
                      <v-btn
                        color="error"
                        variant="outlined"
                        size="small"
                        prepend-icon="mdi-cloud-remove-outline"
                        title="先删除CD2源文件，再删除本地STRM和联动元数据"
                        :loading="deletingAction === `${item.path}:source`"
                        :disabled="!!deletingAction"
                        @click="executeMissingDelete(item, 'source')"
                      >
                        源文件+本地
                      </v-btn>
                      <v-btn
                        v-if="isEpisodeGroupAvailable(item, group)"
                        color="error"
                        variant="tonal"
                        size="small"
                        prepend-icon="mdi-delete-alert-outline"
                        :loading="deletingAction === `${item.path}:group`"
                        :disabled="!!deletingAction"
                        @click="executeMissingDelete(item, 'group')"
                      >
                        同格式整组
                      </v-btn>
                      <v-btn
                        v-if="isEpisodeGroupAvailable(item, group)"
                        color="error"
                        size="small"
                        prepend-icon="mdi-cloud-remove-outline"
                        title="删除同格式整组的CD2源文件、本地STRM和联动元数据"
                        :loading="deletingAction === `${item.path}:group_source`"
                        :disabled="!!deletingAction"
                        @click="executeMissingDelete(item, 'group_source')"
                      >
                        整组+源文件
                      </v-btn>
                    </div>
                  </div>
                </div>
              </v-expansion-panel-text>
            </v-expansion-panel>
          </v-expansion-panels>
          <v-pagination
            v-if="state.missing.page_count > 1"
            v-model="missingPage"
            :length="state.missing.page_count"
            density="comfortable"
            class="pagination"
            @update:model-value="loadState"
          />
        </v-window-item>

        <v-window-item value="orphan">
          <div class="scan-row">
            <div class="scan-copy">
              <div class="text-subtitle-2">多余元数据扫描范围</div>
              <v-select
                :model-value="orphanCategorySelection"
                :items="state.categories"
                item-title="title"
                item-value="value"
                label="选择二级分类"
                variant="outlined"
                density="compact"
                multiple
                chips
                closable-chips
                hide-details
                class="scan-select"
                @update:model-value="updateCategorySelection('orphan', $event)"
              />
            </div>
            <v-btn
              color="primary"
              prepend-icon="mdi-file-search-outline"
              :loading="scanRunning && state.scan_kind === 'orphan'"
              :disabled="scanRunning || !orphanCategorySelection.length"
              @click="startScan('orphan')"
            >
              扫描多余元数据
            </v-btn>
          </div>
          <div v-if="state.orphan.total" class="orphan-toolbar">
            <span class="text-body-2 text-medium-emphasis">
              已选择 {{ selectedOrphanPaths.length }} 项，共 {{ state.orphan.total }} 个文件
            </span>
            <v-btn
              color="error"
              prepend-icon="mdi-delete-sweep-outline"
              :loading="orphanDeleteDialog.executing"
              :disabled="orphanDeleteDialog.executing || !selectedOrphanPaths.length"
              @click="openSelectedOrphanDelete"
            >
              删除所选
            </v-btn>
          </div>
          <div v-if="!state.orphan.items.length" class="empty-state">
            <v-icon icon="mdi-file-check-outline" size="34" />
            <span>暂无多余元数据结果</span>
          </div>
          <div v-else class="orphan-list">
            <div class="orphan-head">
              <v-checkbox-btn
                :model-value="orphanPageAllSelected"
                :indeterminate="orphanPagePartiallySelected"
                density="compact"
                title="选择当前页"
                @update:model-value="toggleCurrentOrphanPage"
              />
              <span>分类</span>
              <span>文件</span>
              <span>类型</span>
              <span />
            </div>
            <div v-for="item in state.orphan.items" :key="item.path" class="orphan-row">
              <v-checkbox-btn
                :model-value="selectedOrphanPaths.includes(item.path)"
                density="compact"
                :title="`选择 ${item.name}`"
                @update:model-value="toggleOrphanSelection(item.path, $event)"
              />
              <span class="text-medium-emphasis">{{ item.category }}</span>
              <span class="file-name">{{ item.name }}</span>
              <v-chip size="x-small" variant="tonal">{{ item.type }}</v-chip>
              <v-btn
                icon="mdi-delete-outline"
                color="error"
                variant="text"
                size="small"
                title="删除"
                :loading="deletingPath === item.path"
                @click="openOrphanDelete(item)"
              />
            </div>
          </div>
          <v-pagination
            v-if="state.orphan.page_count > 1"
            v-model="orphanPage"
            :length="state.orphan.page_count"
            density="comfortable"
            class="pagination"
            @update:model-value="loadState"
          />
        </v-window-item>
      </v-window>
    </template>

    <v-dialog v-model="deleteDialog.show" max-width="620" persistent>
      <v-card>
        <v-card-title class="dialog-title">
          <span>删除多余元数据</span>
          <v-btn icon="mdi-close" variant="text" size="small" title="关闭" :disabled="deleteDialog.executing" @click="closeDeleteDialog" />
        </v-card-title>
        <v-divider />
        <v-card-text>
          <div class="delete-target">{{ deleteDialog.item?.name }}</div>

          <div v-if="deleteDialog.results.length" class="verify-results">
            <div v-for="result in deleteDialog.results" :key="`${result.path}-${result.name}`" class="verify-row">
              <v-icon :icon="result.verified ? 'mdi-check-circle-outline' : 'mdi-alert-circle-outline'" :color="result.verified ? 'success' : 'error'" size="20" />
              <div>
                <div>{{ result.name }}</div>
                <div class="text-caption text-medium-emphasis">{{ result.message }}</div>
              </div>
            </div>
          </div>
        </v-card-text>
        <v-divider />
        <v-card-actions class="dialog-actions">
          <v-btn variant="text" :disabled="deleteDialog.executing" @click="closeDeleteDialog">取消</v-btn>
          <v-btn
            color="error"
            prepend-icon="mdi-delete"
            :loading="deleteDialog.executing"
            @click="executeDelete"
          >
            {{ deleteDialog.executing ? '正在删除并复核' : '确认删除' }}
          </v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <v-dialog v-model="orphanDeleteDialog.show" max-width="560" persistent>
      <v-card>
        <v-card-title class="dialog-title">
          <span>删除选中的多余元数据</span>
          <v-btn
            icon="mdi-close"
            variant="text"
            size="small"
            title="关闭"
            :disabled="orphanDeleteDialog.executing"
            @click="closeSelectedOrphanDelete"
          />
        </v-card-title>
        <v-divider />
        <v-card-text>
          <v-alert type="warning" variant="tonal" density="compact">
            将删除已选择的 {{ orphanDeleteDialog.paths.length }} 个多余元数据文件，并逐项复核父目录。
          </v-alert>
          <div v-if="orphanDeleteDialog.failedResults.length" class="verify-results">
            <div
              v-for="result in orphanDeleteDialog.failedResults"
              :key="result.path"
              class="verify-row"
            >
              <v-icon icon="mdi-alert-circle-outline" color="error" size="20" />
              <div>
                <div>{{ result.name }}</div>
                <div class="text-caption text-medium-emphasis">{{ result.message }}</div>
              </div>
            </div>
          </div>
        </v-card-text>
        <v-divider />
        <v-card-actions class="dialog-actions">
          <v-btn variant="text" :disabled="orphanDeleteDialog.executing" @click="closeSelectedOrphanDelete">取消</v-btn>
          <v-btn
            color="error"
            prepend-icon="mdi-delete-sweep-outline"
            :loading="orphanDeleteDialog.executing"
            @click="executeSelectedOrphanDelete"
          >
            {{ orphanDeleteDialog.executing ? '正在删除并复核' : '确认删除所选' }}
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
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'

import { EMBY_LIBRARY_ORGANIZER_PLUGIN_ID } from '../utils/pluginId.js'

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
const pluginId = EMBY_LIBRARY_ORGANIZER_PLUGIN_ID
const ALL_CATEGORIES_VALUE = '__all__'
const initialLoading = ref(true)
const refreshing = ref(false)
const activeTab = ref('missing')
const expandedMissingGroup = ref(0)
const missingCategorySelection = ref([])
const orphanCategorySelection = ref([])
const categorySelectionDirty = reactive({ missing: false, orphan: false })
const missingPage = ref(1)
const orphanPage = ref(1)
const deletingPath = ref('')
const deletingAction = ref('')
const selectedOrphanPaths = ref([])
const snackbar = reactive({ show: false, text: '', color: 'success' })
const emptyPage = () => ({ items: [], total: 0, page: 1, page_count: 1, page_size: 20 })
const state = reactive({
  enabled: false,
  status: 'idle',
  scan_running: false,
  scan_kind: '',
  scan_started_at: '',
  scan_finished_at: '',
  task_message: '',
  last_error: '',
  categories: [],
  selected_categories: [],
  selected_missing_categories: [],
  selected_orphan_categories: [],
  missing: emptyPage(),
  orphan: emptyPage(),
})
const deleteDialog = reactive({
  show: false,
  item: null,
  executing: false,
  results: [],
})
const orphanDeleteDialog = reactive({
  show: false,
  executing: false,
  paths: [],
  failedResults: [],
})
let pollTimer = null

const scanRunning = computed(() => state.scan_running || ['queued', 'scanning'].includes(state.status))
const statusText = computed(() => {
  if (state.last_error && state.status === 'failed') return `失败：${state.last_error}`
  if (state.task_message) return state.task_message
  if (!state.enabled) return '插件未启用'
  return '等待操作'
})
const statusTone = computed(() => {
  if (state.status === 'failed') return 'error'
  if (scanRunning.value) return 'working'
  if (!state.enabled) return 'muted'
  return 'success'
})
const orphanPagePaths = computed(() => state.orphan.items.map((item) => item.path))
const orphanPageSelectedCount = computed(() => orphanPagePaths.value.filter(
  (path) => selectedOrphanPaths.value.includes(path),
).length)
const orphanPageAllSelected = computed(() => (
  orphanPagePaths.value.length > 0
  && orphanPageSelectedCount.value === orphanPagePaths.value.length
))
const orphanPagePartiallySelected = computed(() => (
  orphanPageSelectedCount.value > 0
  && !orphanPageAllSelected.value
))
const showMessage = (text, color = 'success') => {
  snackbar.text = text
  snackbar.color = color
  snackbar.show = true
}

const formatTime = (value) => {
  if (!value) return ''
  return value.replace('T', ' ')
}

const formatShortTime = (value) => {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value).replace('T', ' ').slice(11, 16)
  return date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false })
}

const stateUrl = () => {
  const query = new URLSearchParams({
    missing_page: String(missingPage.value),
    orphan_page: String(orphanPage.value),
    page_size: '20',
  })
  return `plugin/${pluginId}/ui_state?${query.toString()}`
}

const loadState = async () => {
  refreshing.value = true
  try {
    const result = await props.api.get(stateUrl())
    if (!result || result.code !== 0) throw new Error(result?.msg || '读取页面状态失败')
    const data = result.data || {}
    Object.assign(state, data)
    if (!categorySelectionDirty.missing) {
      missingCategorySelection.value = [...(
        data.selected_missing_categories?.length
          ? data.selected_missing_categories
          : data.selected_categories || []
      )]
    }
    if (!categorySelectionDirty.orphan) {
      orphanCategorySelection.value = [...(data.selected_orphan_categories || [])]
    }
    const visibleOrphanPaths = new Set((data.orphan?.items || []).map((item) => item.path))
    selectedOrphanPaths.value = selectedOrphanPaths.value.filter(
      (path) => visibleOrphanPaths.has(path),
    )
    schedulePoll(scanRunning.value ? 1200 : 5000)
  } catch (error) {
    showMessage(error?.message || '读取页面状态失败', 'error')
    schedulePoll(5000)
  } finally {
    initialLoading.value = false
    refreshing.value = false
  }
}

const schedulePoll = (delay) => {
  if (pollTimer) window.clearTimeout(pollTimer)
  pollTimer = window.setTimeout(loadState, delay)
}

const startScan = async (kind) => {
  const endpoint = kind === 'missing' ? 'scan_missing_metadata' : 'scan_orphan_metadata'
  const categories = kind === 'missing'
    ? missingCategorySelection.value
    : orphanCategorySelection.value
  try {
    const query = new URLSearchParams({ categories: JSON.stringify(categories) })
    const result = await props.api.post(`plugin/${pluginId}/${endpoint}?${query.toString()}`)
    if (!result || result.code !== 0) throw new Error(result?.msg || '扫描任务提交失败')
    categorySelectionDirty[kind] = false
    if (kind === 'missing') {
      state.selected_missing_categories = [...categories]
      state.selected_categories = [...categories]
    } else {
      state.selected_orphan_categories = [...categories]
    }
    state.status = result.data?.status || 'queued'
    state.scan_running = true
    state.task_message = result.msg
    state.last_error = ''
    showMessage(result.msg || '扫描任务已提交', 'info')
    schedulePoll(500)
  } catch (error) {
    showMessage(error?.message || '扫描任务提交失败', 'error')
  }
}

const updateCategorySelection = (kind, values) => {
  const previous = kind === 'missing'
    ? missingCategorySelection.value
    : orphanCategorySelection.value
  const valuesList = Array.isArray(values) ? [...values] : []
  let selection = valuesList
  if (valuesList.includes(ALL_CATEGORIES_VALUE)) {
    selection = previous.includes(ALL_CATEGORIES_VALUE)
      ? valuesList.filter((value) => value !== ALL_CATEGORIES_VALUE)
      : [ALL_CATEGORIES_VALUE]
  }
  if (kind === 'missing') {
    missingCategorySelection.value = selection
  } else {
    orphanCategorySelection.value = selection
  }
  categorySelectionDirty[kind] = true
}

const isEpisodeGroupAvailable = (item, group) => {
  return item?.season !== '-'
    && group?.library_type === 'tv'
}

const executeMissingDelete = async (item, mode) => {
  const actionKey = `${item.path}:${mode}`
  deletingAction.value = actionKey
  try {
    const isGroup = mode === 'group' || mode === 'group_source'
    const endpoint = isGroup ? 'delete_episode_group' : 'delete_missing_strm'
    const query = new URLSearchParams({
      path: item.path,
      include_sidecars: 'true',
      include_cloud: String(mode === 'source' || mode === 'group_source'),
    })
    const result = await props.api.post(`plugin/${pluginId}/${endpoint}?${query.toString()}`)
    const data = result?.data || {}
    await loadState()
    if (result?.code === 0 && data.verified) {
      showMessage(result.msg || '删除并复核完成', 'success')
      return
    }
    const removed = Number(data.removed_strm_count || 0)
    showMessage(
      removed > 0
        ? `部分完成：${result?.msg || '请检查复核结果'}`
        : (result?.msg || '删除未完成'),
      removed > 0 ? 'warning' : 'error',
    )
  } catch (error) {
    showMessage(error?.message || '删除请求失败', 'error')
  } finally {
    deletingAction.value = ''
  }
}

const openOrphanDelete = (item) => {
  Object.assign(deleteDialog, {
    show: true,
    item,
    executing: false,
    results: [],
  })
}

const closeDeleteDialog = () => {
  if (deleteDialog.executing) return
  deleteDialog.show = false
}

const toggleOrphanSelection = (path, selected) => {
  if (selected) {
    selectedOrphanPaths.value = [...new Set([...selectedOrphanPaths.value, path])]
    return
  }
  selectedOrphanPaths.value = selectedOrphanPaths.value.filter((item) => item !== path)
}

const toggleCurrentOrphanPage = (selected) => {
  if (selected) {
    selectedOrphanPaths.value = [...orphanPagePaths.value]
    return
  }
  selectedOrphanPaths.value = []
}

const openSelectedOrphanDelete = () => {
  if (!selectedOrphanPaths.value.length) return
  Object.assign(orphanDeleteDialog, {
    show: true,
    executing: false,
    paths: [...selectedOrphanPaths.value],
    failedResults: [],
  })
}

const closeSelectedOrphanDelete = () => {
  if (orphanDeleteDialog.executing) return
  orphanDeleteDialog.show = false
}

const executeSelectedOrphanDelete = async () => {
  orphanDeleteDialog.executing = true
  orphanDeleteDialog.failedResults = []
  try {
    const query = new URLSearchParams({
      paths: JSON.stringify(orphanDeleteDialog.paths),
      confirmed: 'true',
    })
    const result = await props.api.post(
      `plugin/${pluginId}/delete_orphan_metadata_batch?${query.toString()}`,
    )
    const data = result?.data || {}
    orphanDeleteDialog.failedResults = (data.local_results || [])
      .filter((item) => !item.verified)
      .slice(0, 10)
    await loadState()
    if (result?.code === 0 && data.verified) {
      showMessage(result.msg || '所选文件删除并复核完成', 'success')
      selectedOrphanPaths.value = []
      orphanDeleteDialog.show = false
      return
    }
    const deletedCount = Number(data.deleted_count || 0)
    const failedCount = Number(data.failed_count || 0)
    showMessage(
      deletedCount > 0
        ? `部分完成：已复核 ${deletedCount} 个，失败 ${failedCount} 个`
        : (result?.msg || '批量删除未完成'),
      deletedCount > 0 ? 'warning' : 'error',
    )
  } catch (error) {
    showMessage(error?.message || '批量删除请求失败', 'error')
  } finally {
    orphanDeleteDialog.executing = false
  }
}

const executeDelete = async () => {
  if (!deleteDialog.item) return
  deleteDialog.executing = true
  deleteDialog.results = []
  deletingPath.value = deleteDialog.item.path
  try {
    const params = { path: deleteDialog.item.path }
    const query = new URLSearchParams(params)
    const result = await props.api.post(`plugin/${pluginId}/delete_orphan_metadata?${query.toString()}`)
    const data = result?.data || {}
    deleteDialog.results = [...(data.cloud_results || []), ...(data.local_results || [])]
    if (result?.code === 0 && data.verified) {
      showMessage(result.msg || '删除并复核完成', 'success')
      await loadState()
      deleteDialog.show = false
    } else {
      showMessage(result?.msg || '删除未完成', 'error')
      await loadState()
    }
  } catch (error) {
    showMessage(error?.message || '删除请求失败', 'error')
  } finally {
    deleteDialog.executing = false
    deletingPath.value = ''
  }
}

onMounted(loadState)
onBeforeUnmount(() => {
  if (pollTimer) window.clearTimeout(pollTimer)
})
</script>

<style scoped>
.plugin-workbench {
  --workbench-muted: rgba(var(--v-theme-on-surface), 0.72);
  display: flex;
  min-height: min(760px, 92vh);
  flex-direction: column;
  overflow: hidden;
  background: rgb(var(--v-theme-surface));
  color: rgb(var(--v-theme-on-surface));
  letter-spacing: 0;
}

.plugin-workbench :deep(.text-medium-emphasis) {
  color: var(--workbench-muted) !important;
  opacity: 1 !important;
}

.page-header,
.scan-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  padding: 18px 22px;
}

.title-block,
.scan-copy,
.group-title {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 4px;
}

.status-line,
.header-actions,
.missing-types {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.status-line {
  font-size: 0.78rem;
}

.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: rgb(var(--v-theme-success));
}

.status-dot.working { background: rgb(var(--v-theme-info)); }
.status-dot.error { background: rgb(var(--v-theme-error)); }
.status-dot.muted { background: rgb(var(--v-theme-on-surface-variant)); }

.scan-row {
  min-height: 74px;
  min-width: 0;
  margin-bottom: 14px;
  padding: 14px 16px;
  border: 1px solid rgba(var(--v-border-color), var(--v-border-opacity));
  border-radius: 6px;
  background: rgba(var(--v-theme-surface-variant), 0.16);
}

.scan-copy {
  flex: 1 1 auto;
}

.scan-select {
  width: min(720px, 100%);
  margin-top: 6px;
}

.task-strip {
  display: flex;
  align-items: center;
  gap: 9px;
  min-height: 42px;
  padding: 9px 22px;
  font-size: 0.86rem;
  color: rgb(var(--v-theme-info));
  background: rgba(var(--v-theme-info), 0.08);
}

.metric-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  border-bottom: 1px solid rgba(var(--v-border-color), var(--v-border-opacity));
  background: rgba(var(--v-theme-surface-variant), 0.1);
}

.metric-cell {
  min-width: 0;
  padding: 12px 18px;
  border-inline-end: 1px solid rgba(var(--v-border-color), var(--v-border-opacity));
}

.metric-cell:last-child {
  border-inline-end: 0;
}

.metric-cell strong,
.metric-cell span {
  display: block;
}

.metric-cell strong {
  font-size: 1.15rem;
  font-variant-numeric: tabular-nums;
}

.metric-cell span {
  margin-top: 2px;
  color: var(--workbench-muted);
  font-size: 0.75rem;
}

.task-strip.error {
  color: rgb(var(--v-theme-error));
  background: rgba(var(--v-theme-error), 0.08);
}

.result-tabs {
  padding: 0 14px;
}

.tab-count {
  margin-left: 7px;
  color: var(--workbench-muted);
  font-size: 0.75rem;
}

.result-window {
  padding: 18px 22px 24px;
}

.orphan-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 12px;
}

.result-panels :deep(.v-expansion-panel) {
  border-bottom: 1px solid rgba(var(--v-border-color), var(--v-border-opacity));
  border-radius: 0;
  box-shadow: none;
}

.episode-list,
.orphan-list,
.verify-results {
  display: flex;
  flex-direction: column;
}

.episode-row,
.orphan-row,
.orphan-head,
.verify-row {
  display: grid;
  align-items: center;
  gap: 12px;
  min-height: 50px;
  border-bottom: 1px solid rgba(var(--v-border-color), 0.18);
}

.episode-row {
  grid-template-columns: minmax(0, 1fr) minmax(430px, auto);
}

.episode-main {
  display: grid;
  grid-template-columns: minmax(72px, auto) minmax(180px, 1fr) auto;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.season-label,
.episode-name,
.file-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.season-label {
  color: var(--workbench-muted);
  font-size: 0.78rem;
}

.episode-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 6px;
  min-width: 0;
  flex-wrap: wrap;
}

.episode-actions .v-btn {
  flex: 0 0 auto;
}

.header-actions :deep(.v-btn),
.episode-actions :deep(.v-btn),
.orphan-row :deep(.v-btn) {
  min-width: 44px;
  min-height: 44px;
}

.orphan-head,
.orphan-row {
  grid-template-columns: 36px minmax(130px, 0.7fr) minmax(220px, 1.5fr) minmax(72px, 0.4fr) 40px;
}

.orphan-head {
  min-height: 38px;
  color: var(--workbench-muted);
  font-size: 0.75rem;
  font-weight: 600;
}

.empty-state,
.initial-loading {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  min-height: 170px;
  color: var(--workbench-muted);
}

.pagination {
  margin-top: 20px;
}

.dialog-title,
.dialog-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.dialog-actions {
  justify-content: flex-end;
  padding: 12px 18px;
}

.delete-target {
  overflow-wrap: anywhere;
  margin-bottom: 8px;
  font-weight: 600;
}

.verify-results {
  max-height: 230px;
  overflow-y: auto;
  margin-top: 16px;
}

.verify-row {
  grid-template-columns: 24px minmax(0, 1fr);
  padding: 8px 0;
}

@media (max-width: 1100px) {
  .episode-row {
    grid-template-columns: minmax(0, 1fr);
    padding: 10px 0;
  }

  .episode-actions {
    justify-content: flex-start;
  }
}

@media (max-width: 760px) {
  .metric-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .metric-cell:nth-child(2) {
    border-inline-end: 0;
  }

  .metric-cell:nth-child(-n + 2) {
    border-bottom: 1px solid rgba(var(--v-border-color), var(--v-border-opacity));
  }

  .page-header,
  .scan-row {
    padding-right: 16px;
    padding-left: 16px;
  }

  .page-header {
    align-items: flex-start;
    gap: 8px;
  }

  .page-header .title-block {
    flex: 1 1 auto;
  }

  .header-actions {
    flex: 0 0 auto;
    flex-wrap: nowrap;
    gap: 0;
  }

  .scan-row {
    align-items: stretch;
    flex-direction: column;
  }

  .scan-row > .v-btn {
    width: 100%;
    min-height: 44px;
  }

  .result-window {
    padding-right: 12px;
    padding-left: 12px;
  }

  .orphan-toolbar {
    align-items: stretch;
    flex-direction: column;
  }

  .orphan-toolbar .v-btn {
    width: 100%;
  }

  .episode-main {
    grid-template-columns: minmax(0, 1fr) auto;
  }

  .episode-actions {
    align-items: stretch;
    flex-direction: column;
  }

  .episode-actions .v-btn {
    flex: 1 1 auto;
  }

  .season-label {
    grid-column: 1 / -1;
  }

  .orphan-head {
    display: none;
  }

  .orphan-row {
    grid-template-columns: 32px minmax(0, 1fr) auto 40px;
    gap: 6px 10px;
    padding: 10px 0;
  }

  .orphan-row > :first-child {
    grid-column: 1;
    grid-row: 1 / 3;
  }

  .orphan-row > :nth-child(2) {
    grid-column: 2;
    grid-row: 1;
    font-size: 0.75rem;
  }

  .orphan-row .file-name {
    grid-column: 2 / 4;
    grid-row: 2;
    overflow: visible;
    overflow-wrap: anywhere;
    white-space: normal;
  }

  .orphan-row > .v-chip {
    grid-column: 3;
    grid-row: 1;
  }

  .orphan-row > .v-btn {
    grid-column: 4;
    grid-row: 1 / 3;
  }
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
