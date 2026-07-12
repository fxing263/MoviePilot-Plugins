<template>
  <v-app>
    <main class="preview-shell">
      <component
        :is="activeComponent"
        :api="previewApi"
        :initial-config="previewConfig"
        @switch="showConfig"
        @close="handleClose"
        @save="saveConfig"
      />
    </main>
    <v-snackbar v-model="snackbar.show" :color="snackbar.color" timeout="3000">
      {{ snackbar.text }}
    </v-snackbar>
  </v-app>
</template>

<script setup>
import { onBeforeUnmount, onMounted, reactive, shallowRef } from 'vue'

import Config from './components/Config.vue'
import Page from './components/Page.vue'

const activeComponent = shallowRef(Page)
const snackbar = reactive({ show: false, text: '', color: 'info' })
const timers = new Set()
let pendingDeleteItemIds = []
const previewConfig = reactive({ enabled: true, root_dir: '/media/downloads' })
const previewItems = reactive([
  {
    item_id: 'alpha-video',
    relative_path: '电影/示例影片/Example.Movie.2026.mkv',
    absolute_path: '/media/downloads/电影/示例影片/Example.Movie.2026.mkv',
    name: 'Example.Movie.2026.mkv',
    parent: '电影/示例影片',
    suffix: '.mkv',
    size: 8_967_241_728,
    modified_at: '2026-07-11T21:16:04+08:00',
  },
  {
    item_id: 'alpha-poster',
    relative_path: '电影/示例影片/Example.Movie.2026-poster.jpg',
    absolute_path: '/media/downloads/电影/示例影片/Example.Movie.2026-poster.jpg',
    name: 'Example.Movie.2026-poster.jpg',
    parent: '电影/示例影片',
    suffix: '.jpg',
    size: 428_310,
    modified_at: '2026-07-11T21:15:42+08:00',
  },
  {
    item_id: 'alpha-json',
    relative_path: '电影/示例影片/Example.Movie.2026-mediainfo.json',
    absolute_path: '/media/downloads/电影/示例影片/Example.Movie.2026-mediainfo.json',
    name: 'Example.Movie.2026-mediainfo.json',
    parent: '电影/示例影片',
    suffix: '.json',
    size: 12_860,
    modified_at: '2026-07-11T21:15:58+08:00',
  },
])
const previewState = reactive({
  enabled: true,
  task_status: 'succeeded',
  task_kind: 'search',
  task_message: '搜索完成，共匹配 3 个文件',
  task_started_at: '2026-07-11T21:16:03+08:00',
  task_finished_at: '2026-07-11T21:16:04+08:00',
  last_error: '',
  search: {
    query: 'Example.Movie',
    scanned_files: 2841,
    matched_files: 3,
    visible_files: 3,
    failed_entries: 0,
    truncated: false,
    generated_at: '2026-07-11T21:16:04+08:00',
    message: '搜索完成，共匹配 3 个文件',
  },
  last_report: {},
  logs: [],
  config: { root_dir: '/media/downloads' },
})

const clone = (value) => JSON.parse(JSON.stringify(value))

const setPreviewTimeout = (callback, delay) => {
  const timer = window.setTimeout(() => {
    timers.delete(timer)
    callback()
  }, delay)
  timers.add(timer)
}

const previewApi = {
  get: async (url) => {
    const parsedUrl = new URL(url, 'http://preview.local')
    if (parsedUrl.pathname.endsWith('/status')) {
      return { success: true, message: '', data: clone(previewState) }
    }
    if (parsedUrl.pathname.endsWith('/results')) {
      return {
        success: true,
        message: '',
        data: {
          items: clone(previewItems),
          total: previewItems.length,
          page: 1,
          page_size: 50,
          page_count: 1,
          summary: clone(previewState.search),
        },
      }
    }
    if (parsedUrl.pathname.endsWith('/delete-preview')) {
      const item = previewItems.find(
        (candidate) => candidate.item_id === parsedUrl.searchParams.get('item_id'),
      )
      if (!item) return { success: false, message: '该文件不在当前搜索结果中', data: null }
      return {
        success: true,
        message: '删除预览已生成',
        data: {
          item_id: item.item_id,
          relative_path: item.relative_path,
          absolute_path: item.absolute_path,
          size: item.size,
          modified_at: item.modified_at,
          confirm_token: `preview-${item.item_id}`,
          blocked_reasons: [],
        },
      }
    }
    return { success: false, message: '未找到预览接口', data: null }
  },
  post: async (url, data = {}) => {
    const parsedUrl = new URL(url, 'http://preview.local')
    if (parsedUrl.pathname.endsWith('/search')) {
      const query = parsedUrl.searchParams.get('query') || ''
      previewState.task_status = 'queued'
      previewState.task_kind = 'search'
      previewState.task_message = `搜索“${query}”已排队`
      setPreviewTimeout(() => {
        previewState.task_status = 'running'
        previewState.task_message = `搜索“${query}”正在执行`
      }, 400)
      setPreviewTimeout(() => {
        previewState.task_status = 'succeeded'
        previewState.task_message = `搜索完成，共匹配 ${previewItems.length} 个文件`
        previewState.task_finished_at = new Date().toISOString()
        previewState.search.query = query
        previewState.search.generated_at = previewState.task_finished_at
        previewState.search.matched_files = previewItems.length
        previewState.search.visible_files = previewItems.length
        previewState.search.message = previewState.task_message
      }, 1300)
      return { success: true, message: '搜索任务已排队', data: { status: 'queued', kind: 'search' } }
    }
    if (parsedUrl.pathname.endsWith('/delete-batch-preview')) {
      const requestedIds = Array.isArray(data.item_ids) ? data.item_ids : []
      const excludedIds = new Set(Array.isArray(data.excluded_item_ids) ? data.excluded_item_ids : [])
      const selectedItems = data.select_all
        ? previewItems.filter((item) => !excludedIds.has(item.item_id))
        : previewItems.filter((item) => requestedIds.includes(item.item_id))
      if (!selectedItems.length) return { success: false, message: '请至少选择一个源文件', data: null }
      pendingDeleteItemIds = selectedItems.map((item) => item.item_id)
      return {
        success: true,
        message: `已生成 ${selectedItems.length} 个源文件的删除预览`,
        data: {
          selected_count: selectedItems.length,
          ready_count: selectedItems.length,
          blocked_count: 0,
          total_size: selectedItems.reduce((total, item) => total + item.size, 0),
          confirm_token: 'preview-batch-token',
          blocked_reasons: [],
          items: clone(selectedItems),
          preview_truncated: false,
          permanent: true,
        },
      }
    }
    if (parsedUrl.pathname.endsWith('/delete-batch')) {
      const selectedItems = previewItems.filter((item) => pendingDeleteItemIds.includes(item.item_id))
      if (!data.confirmed || data.confirm_token !== 'preview-batch-token' || !selectedItems.length) {
        return { success: false, message: '确认令牌无效或已过期', data: null }
      }
      previewState.task_status = 'queued'
      previewState.task_kind = 'delete_batch'
      previewState.task_message = `删除 ${selectedItems.length} 个源文件已排队`
      setPreviewTimeout(() => {
        previewState.task_status = 'running'
        previewState.task_message = `正在删除并复核 ${selectedItems.length} 个源文件`
      }, 350)
      setPreviewTimeout(() => {
        const selectedIds = new Set(pendingDeleteItemIds)
        for (let index = previewItems.length - 1; index >= 0; index -= 1) {
          if (selectedIds.has(previewItems[index].item_id)) previewItems.splice(index, 1)
        }
        previewState.search.matched_files = previewItems.length
        previewState.search.visible_files = previewItems.length
        previewState.task_status = 'succeeded'
        previewState.task_message = `批量删除完成，${selectedItems.length} 个源文件均已删除并通过复核`
        previewState.task_finished_at = new Date().toISOString()
        previewState.last_report = {
          kind: 'delete_batch',
          success: true,
          verified: true,
          message: previewState.task_message,
          requested_count: selectedItems.length,
          verified_count: selectedItems.length,
        }
        pendingDeleteItemIds = []
      }, 1200)
      return { success: true, message: '批量删除任务已排队', data: { status: 'queued', kind: 'delete_batch' } }
    }
    if (parsedUrl.pathname.endsWith('/delete')) {
      const itemId = parsedUrl.searchParams.get('item_id')
      const item = previewItems.find((candidate) => candidate.item_id === itemId)
      if (!item) return { success: false, message: '文件不存在', data: null }
      previewState.task_status = 'queued'
      previewState.task_kind = 'delete'
      previewState.task_message = `删除 ${item.name} 已排队`
      setPreviewTimeout(() => {
        previewState.task_status = 'running'
        previewState.task_message = `正在删除并复核 ${item.name}`
      }, 350)
      setPreviewTimeout(() => {
        const index = previewItems.findIndex((candidate) => candidate.item_id === itemId)
        if (index >= 0) previewItems.splice(index, 1)
        previewState.search.matched_files = previewItems.length
        previewState.search.visible_files = previewItems.length
        previewState.task_status = 'succeeded'
        previewState.task_message = '文件已删除并通过复核'
        previewState.task_finished_at = new Date().toISOString()
        previewState.last_report = {
          kind: 'delete',
          success: true,
          verified: true,
          message: previewState.task_message,
          result: { relative_path: item.relative_path, verified: true },
        }
      }, 1200)
      return { success: true, message: '删除任务已排队', data: { status: 'queued', kind: 'delete' } }
    }
    return { success: false, message: '未找到预览接口', data: null }
  },
}

const showConfig = () => {
  activeComponent.value = Config
}

const handleClose = () => {
  if (activeComponent.value === Config) {
    activeComponent.value = Page
    return
  }
  snackbar.text = '已触发关闭事件'
  snackbar.color = 'info'
  snackbar.show = true
}

const saveConfig = (config) => {
  Object.assign(previewConfig, config)
  previewState.enabled = Boolean(config.enabled)
  previewState.config.root_dir = config.root_dir
  activeComponent.value = Page
  snackbar.text = '预览配置已保存'
  snackbar.color = 'success'
  snackbar.show = true
}

onMounted(() => {
  const params = new URLSearchParams(window.location.search)
  if (params.get('view') === 'config') activeComponent.value = Config
})

onBeforeUnmount(() => {
  for (const timer of timers) window.clearTimeout(timer)
  timers.clear()
})
</script>

<style>
html,
body,
#app {
  min-height: 100%;
  margin: 0;
}

.preview-shell {
  width: min(1120px, calc(100% - 32px));
  min-height: 720px;
  margin: 24px auto;
  overflow: hidden;
  border: 1px solid rgba(var(--v-border-color), var(--v-border-opacity));
  border-radius: 8px;
  background: rgb(var(--v-theme-surface));
  box-shadow: 0 12px 32px rgba(15, 23, 42, 0.08);
}

@media (max-width: 700px) {
  .preview-shell {
    width: 100%;
    min-height: 100vh;
    margin: 0;
    border: 0;
    border-radius: 0;
    box-shadow: none;
  }
}
</style>
