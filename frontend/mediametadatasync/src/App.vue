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
    <v-snackbar v-model="snackbar.show" :color="snackbar.color" timeout="3200">
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
const previewConfig = reactive({
  enabled: true,
  monitor_enabled: true,
  reverse_sync_enabled: true,
  source_dir: '/media/9kg',
  target_dir: '/media/番号系列',
  other_category: '其他',
  settle_seconds: 2,
  sync_extensions: [
    '.strm',
    '.nfo',
    '.jpg',
    '.jpeg',
    '.png',
    '.webp',
    '.gif',
    '.json',
  ],
  cloud_mount_paths: ['/CloudNAS/CloudDrive'],
  max_delete_files: 100,
})
const previewState = reactive({
  enabled: true,
  monitor_enabled: true,
  monitoring: true,
  task_status: 'completed',
  task_kind: 'all',
  task_message: '双向全量同步完成',
  task_started_at: '2026-07-11T18:20:06+08:00',
  task_finished_at: '2026-07-11T18:20:09+08:00',
  last_error: '',
  pending_source_count: 2,
  pending_json_count: 0,
  activated_count: 38,
  not_ready: [
    {
      path: '/media/9kg/示例合集/NEW-204',
      reason: '未找到同名 .strm 与 .nfo',
    },
    {
      path: '/media/9kg/示例合集/XS-007',
      reason: 'NFO 文件仍在写入，等待目录稳定',
    },
  ],
  stats: {
    scanned_directories: 40,
    ready_directories: 38,
    forward_copied: 12,
    forward_skipped: 146,
    reverse_copied: 3,
    missing_targets: 1,
  },
  logs: [
    '[18:20:06] 开始执行双向全量同步',
    '[18:20:07] 复制 /media/9kg/示例合集/ABC-123/ABC-123.nfo',
    '[18:20:08] 跳过未变化文件 ABC-123.strm',
    '[18:20:09] JSON 回写完成，共更新 3 个目标',
  ],
  config: {
    source_dir: '/media/9kg',
    target_dir: '/media/番号系列',
  },
  missing_metadata: {
    missing_items: 3,
    missing_nfo: 2,
    missing_mediainfo: 2,
    scanned_strm_files: 41,
    generated_at: '2026-07-11T18:22:09+08:00',
    message: '缺失元数据扫描完成',
  },
  last_report: {
    kind: 'all',
    finished_at: '2026-07-11T18:20:09+08:00',
    copied: 15,
    skipped: 146,
    failed: 0,
    not_ready: 2,
  },
})
const previewMissingItems = reactive([
  {
    item_id: 'abc123',
    number: 'ABC-123',
    file_name: 'ABC-123.strm',
    owner_names: ['示例合集'],
    source_paths: ['/media/9kg/示例合集/ABC-123/ABC-123.strm'],
    missing_types: ['MediaInfo'],
    cloud_ready: true,
    cloud_message: '',
  },
  {
    item_id: 'new204',
    number: 'NEW-204',
    file_name: 'NEW-204.strm',
    owner_names: ['演员甲', '演员乙'],
    source_paths: [
      '/media/9kg/演员甲/NEW-204/NEW-204.strm',
      '/media/9kg/演员乙/NEW-204/NEW-204.strm',
    ],
    missing_types: ['NFO', 'MediaInfo'],
    cloud_ready: true,
    cloud_message: '',
  },
  {
    item_id: 'xs007',
    number: 'XS-007',
    file_name: 'XS-007.strm',
    owner_names: ['待整理'],
    source_paths: ['/media/9kg/待整理/XS-007/XS-007.strm'],
    missing_types: ['NFO'],
    cloud_ready: false,
    cloud_message: '网盘路径超出允许挂载根目录',
  },
])

const clone = (value) => JSON.parse(JSON.stringify(value))

const setPreviewTimeout = (callback, delay) => {
  const timer = window.setTimeout(() => {
    timers.delete(timer)
    callback()
  }, delay)
  timers.add(timer)
}

const finishPreviewTask = (kind, label) => {
  previewState.task_status = 'completed'
  previewState.task_message = `${label}完成`
  previewState.task_finished_at = new Date().toISOString()
  previewState.stats.forward_copied += kind === 'reverse' ? 0 : 2
  previewState.stats.reverse_copied += kind === 'forward' ? 0 : 1
  previewState.logs.push(`[${new Date().toLocaleTimeString('zh-CN', { hour12: false })}] ${label}完成`)
  previewState.last_report = {
    kind,
    finished_at: previewState.task_finished_at,
    copied: kind === 'reverse' ? 1 : 2,
    skipped: 9,
    failed: 0,
  }
}

const refreshPreviewMissingSummary = () => {
  previewState.missing_metadata.missing_items = previewMissingItems.length
  previewState.missing_metadata.missing_nfo = previewMissingItems.filter(
    (item) => item.missing_types.includes('NFO'),
  ).length
  previewState.missing_metadata.missing_mediainfo = previewMissingItems.filter(
    (item) => item.missing_types.includes('MediaInfo'),
  ).length
}

const previewDeletePlan = (item) => {
  const number = item.number
  const fileStem = item.file_name.replace(/\.strm$/i, '')
  const blockedReasons = item.cloud_ready ? [] : [item.cloud_message || '网盘路径不可删除']
  return {
    item_id: item.item_id,
    number,
    file_name: item.file_name,
    cloud_files: item.cloud_ready ? [`/CloudNAS/CloudDrive/媒体/${item.file_name.replace(/\.strm$/i, '.mp4')}`] : [],
    target_files: [
      `/media/番号系列/${number[0]}/${number}/${item.file_name}`,
      `/media/番号系列/${number[0]}/${number}/${fileStem}-poster.jpg`,
    ],
    source_files: item.source_paths,
    blocked_reasons: blockedReasons,
    confirm_token: blockedReasons.length ? '' : `preview-${item.item_id}`,
  }
}

const previewApi = {
  get: async (url) => {
    const parsedUrl = new URL(url, 'http://preview.local')
    if (parsedUrl.pathname.endsWith('/status')) {
      return { success: true, message: '', data: clone(previewState) }
    }
    if (parsedUrl.pathname.endsWith('/missing/items')) {
      const query = String(parsedUrl.searchParams.get('query') || '').trim().toLowerCase()
      const items = previewMissingItems.filter((item) => (
        !query
        || `${item.number} ${item.file_name} ${item.owner_names.join(' ')}`.toLowerCase().includes(query)
      ))
      return {
        success: true,
        message: '',
        data: {
          items: clone(items),
          total: items.length,
          page: 1,
          page_count: 1,
          page_size: 30,
          summary: clone(previewState.missing_metadata),
        },
      }
    }
    if (parsedUrl.pathname.endsWith('/missing/delete-preview')) {
      const item = previewMissingItems.find(
        (candidate) => candidate.item_id === parsedUrl.searchParams.get('item_id'),
      )
      if (!item) return { success: false, message: '记录不存在', data: null }
      return { success: true, message: '删除预览已生成', data: previewDeletePlan(item) }
    }
    return { success: false, message: '未找到预览接口', data: null }
  },
  post: async (url) => {
    const parsedUrl = new URL(url, 'http://preview.local')
    const path = parsedUrl.pathname
    if (path.endsWith('/monitor/start')) {
      previewState.monitoring = true
      previewState.logs.push('[预览] 实时监控已启动')
      return { success: true, message: '实时监控已启动', data: { monitoring: true } }
    }
    if (path.endsWith('/monitor/stop')) {
      previewState.monitoring = false
      previewState.logs.push('[预览] 实时监控已停止')
      return { success: true, message: '实时监控已停止', data: { monitoring: false } }
    }

    if (path.endsWith('/missing/scan')) {
      previewState.task_status = 'queued'
      previewState.task_kind = 'missing_scan'
      previewState.task_message = '缺失元数据扫描已排队'
      previewState.task_started_at = new Date().toISOString()
      previewState.task_finished_at = ''
      setPreviewTimeout(() => {
        previewState.task_status = 'running'
        previewState.task_message = '正在检查 STRM 元数据'
      }, 500)
      setPreviewTimeout(() => {
        previewState.task_status = 'succeeded'
        previewState.task_message = '缺失元数据扫描完成'
        previewState.task_finished_at = new Date().toISOString()
        previewState.missing_metadata.generated_at = previewState.task_finished_at
        refreshPreviewMissingSummary()
      }, 1800)
      return { success: true, message: '缺失元数据扫描已排队', data: { status: 'queued' } }
    }

    if (path.endsWith('/missing/delete')) {
      const itemId = parsedUrl.searchParams.get('item_id')
      const item = previewMissingItems.find((candidate) => candidate.item_id === itemId)
      if (!item) return { success: false, message: '记录不存在', data: null }
      previewState.task_status = 'queued'
      previewState.task_kind = 'missing_delete'
      previewState.task_message = `删除 ${item.number}/${item.file_name} 已排队`
      previewState.task_started_at = new Date().toISOString()
      previewState.task_finished_at = ''
      setPreviewTimeout(() => {
        previewState.task_status = 'running'
        previewState.task_message = '正在删除并复核三端文件'
      }, 450)
      setPreviewTimeout(() => {
        const index = previewMissingItems.findIndex((candidate) => candidate.item_id === itemId)
        if (index >= 0) previewMissingItems.splice(index, 1)
        refreshPreviewMissingSummary()
        previewState.task_status = 'succeeded'
        previewState.task_message = `三端删除并复核完成：${item.number}/${item.file_name}`
        previewState.task_finished_at = new Date().toISOString()
        previewState.last_report = {
          kind: 'missing_delete',
          success: true,
          verified: true,
          message: previewState.task_message,
          cloud_results: [{ verified: true }],
          target_results: [{ verified: true }, { verified: true }],
          source_results: item.source_paths.map(() => ({ verified: true })),
        }
      }, 1800)
      return { success: true, message: '三端删除任务已排队', data: { status: 'queued' } }
    }

    const action = path.endsWith('/sync/forward')
      ? { kind: 'forward', label: '正向全量同步' }
      : path.endsWith('/sync/reverse')
        ? { kind: 'reverse', label: 'JSON 回写' }
        : { kind: 'all', label: '双向全量同步' }
    previewState.task_status = 'queued'
    previewState.task_kind = action.kind
    previewState.task_message = `${action.label}已进入后台队列`
    previewState.task_started_at = new Date().toISOString()
    previewState.task_finished_at = ''
    previewState.last_error = ''
    previewState.logs.push(`[预览] ${action.label}已提交`)
    setPreviewTimeout(() => {
      previewState.task_status = 'running'
      previewState.task_message = `${action.label}正在执行`
    }, 700)
    setPreviewTimeout(() => finishPreviewTask(action.kind, action.label), 2500)
    return {
      success: true,
      message: `${action.label}已提交`,
      data: { task_status: 'queued' },
    }
  },
}

const showMessage = (text, color = 'info') => {
  snackbar.text = text
  snackbar.color = color
  snackbar.show = true
}

const showConfig = () => {
  activeComponent.value = Config
}

const handleClose = () => {
  if (activeComponent.value === Config) {
    activeComponent.value = Page
    return
  }
  showMessage('已触发关闭事件')
}

const saveConfig = (config) => {
  Object.assign(previewConfig, config)
  previewState.enabled = Boolean(config.enabled)
  previewState.monitor_enabled = Boolean(config.monitor_enabled)
  if (!previewState.monitor_enabled) previewState.monitoring = false
  previewState.config = {
    source_dir: config.source_dir,
    target_dir: config.target_dir,
  }
  activeComponent.value = Page
  showMessage('预览配置已保存', 'success')
}

onMounted(() => {
  const params = new URLSearchParams(window.location.search)
  if (params.get('view') === 'config') activeComponent.value = Config
  const tab = params.get('tab')
  if (tab) {
    setPreviewTimeout(() => {
      document.querySelector(`[value="${tab}"]`)?.click()
    }, 350)
  }
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
