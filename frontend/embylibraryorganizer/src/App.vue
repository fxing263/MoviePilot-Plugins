<template>
  <v-app>
    <main class="preview-shell">
      <component
        :is="activeComponent"
        :api="previewApi"
        :initial-config="previewConfig"
        @switch="switchComponent"
        @close="showMessage('已触发关闭事件')"
        @save="saveConfig"
      />
    </main>
    <v-snackbar v-model="snackbar.show" :color="snackbar.color">
      {{ snackbar.text }}
    </v-snackbar>
  </v-app>
</template>

<script setup>
import { onMounted, reactive, shallowRef } from 'vue'

import Config from './components/Config.vue'
import Page from './components/Page.vue'

const activeComponent = shallowRef(Page)
const snackbar = reactive({ show: false, text: '', color: 'info' })
const previewConfig = reactive({
  enabled: true,
  library_paths: '/media/strm',
  bluray_library_paths: '/media/bluray',
  missing_metadata_categories: [
    '/media/strm/电影/华语电影',
    '/media/strm/电视剧/欧美剧',
  ],
  orphan_metadata_categories: [
    '/media/strm/电影/华语电影',
  ],
  cd2_mount_paths: '/CloudNAS/CloudDrive',
  max_delete_count: 20,
  dry_run: true,
  require_confirm: true,
})

const previewState = reactive({
  enabled: true,
  status: 'idle',
  scan_running: false,
  scan_kind: 'missing',
  scan_started_at: '2026-07-11T16:42:10',
  scan_finished_at: '2026-07-11T16:42:14',
  task_message: '缺失元数据查询完成，发现7项结果',
  last_error: '',
  categories: [
    { title: '全部（全量）', value: '__all__', type: 'all' },
    { title: '电影 / 华语电影', value: '/media/strm/电影/华语电影', type: 'movie' },
    { title: '电影 / 欧美电影', value: '/media/strm/电影/欧美电影', type: 'movie' },
    { title: '电视剧 / 欧美剧', value: '/media/strm/电视剧/欧美剧', type: 'tv' },
    { title: '动漫 / 日本动画', value: '/media/strm/动漫/日本动画', type: 'anime' },
    { title: '蓝光', value: '__bluray__', type: 'movie' },
  ],
  selected_categories: previewConfig.missing_metadata_categories,
  selected_missing_categories: previewConfig.missing_metadata_categories,
  selected_orphan_categories: previewConfig.orphan_metadata_categories,
  missing: {
    total: 3,
    page: 1,
    page_count: 1,
    page_size: 20,
    items: [
      {
        title: '边水往事 (2024)',
        category: '电视剧 / 欧美剧',
        items: [
          { season: 'Season 01', name: '边水往事 S01E01.strm', path: '/media/strm/电视剧/欧美剧/边水往事/Season 01/边水往事 S01E01.strm', missing: ['NFO'] },
          { season: 'Season 01', name: '边水往事 S01E02.strm', path: '/media/strm/电视剧/欧美剧/边水往事/Season 01/边水往事 S01E02.strm', missing: ['NFO', 'JSON'] },
        ],
      },
      {
        title: '年会不能停！ (2023)',
        category: '电影 / 华语电影',
        items: [
          { season: '-', name: '年会不能停！ (2023).strm', path: '/media/strm/电影/华语电影/年会不能停/年会不能停！ (2023).strm', missing: ['JSON'] },
        ],
      },
    ],
  },
  orphan: {
    total: 2,
    page: 1,
    page_count: 1,
    page_size: 20,
    items: [
      { category: '电影 / 华语电影', name: '旧文件.nfo', path: '/media/strm/电影/华语电影/旧文件.nfo', type: 'NFO' },
      { category: '电视剧 / 欧美剧', name: '旧剧集 S01E03-mediainfo.json', path: '/media/strm/电视剧/欧美剧/旧剧集/Season 01/旧剧集 S01E03-mediainfo.json', type: 'JSON' },
    ],
  },
})

const clone = (value) => JSON.parse(JSON.stringify(value))

const previewApi = {
  get: async (url) => {
    if (url.includes('/categories')) {
      return { code: 0, data: clone(previewState.categories) }
    }
    if (url.includes('/delete_preview')) {
      const isGroup = url.includes('episode_group=true')
      const withCloud = url.includes('include_cloud=true')
      return {
        code: 0,
        data: {
          strm_count: isGroup ? 2 : 1,
          local_count: isGroup ? 6 : 3,
          cloud_count: withCloud ? (isGroup ? 2 : 1) : 0,
        },
      }
    }
    return { code: 0, data: clone(previewState) }
  },
  post: async (url) => {
    if (url.includes('/categories/preview')) {
      return { code: 0, data: clone(previewState.categories) }
    }
    if (url.includes('/scan_')) {
      previewState.status = 'scanning'
      previewState.scan_running = true
      previewState.task_message = url.includes('missing')
        ? '缺失元数据查询正在执行'
        : '多余元数据扫描正在执行'
      window.setTimeout(() => {
        previewState.status = 'idle'
        previewState.scan_running = false
        previewState.task_message = '扫描完成，预览数据已刷新'
      }, 1800)
      return { code: 0, msg: '扫描任务已提交', data: { status: 'scanning' } }
    }
    return {
      code: 0,
      msg: '删除并复核完成',
      data: {
        verified: true,
        removed_strm_count: 1,
        cloud_results: [],
        local_results: [
          { path: '/preview/item.strm', name: '预览文件.strm', verified: true, message: '已删除并通过父目录复核' },
        ],
      },
    }
  },
}

const showMessage = (text, color = 'info') => {
  snackbar.text = text
  snackbar.color = color
  snackbar.show = true
}

const switchComponent = () => {
  activeComponent.value = activeComponent.value === Page ? Config : Page
}

const saveConfig = (config) => {
  Object.assign(previewConfig, config)
  previewState.selected_categories = clone(config.missing_metadata_categories || [])
  previewState.selected_missing_categories = clone(config.missing_metadata_categories || [])
  previewState.selected_orphan_categories = clone(config.orphan_metadata_categories || [])
  activeComponent.value = Page
  showMessage('预览配置已保存', 'success')
}

onMounted(() => {
  const params = new URLSearchParams(window.location.search)
  if (params.get('view') === 'config') activeComponent.value = Config
  if (params.get('tab') === 'orphan') {
    window.setTimeout(() => {
      document.querySelectorAll('[role="tab"]')[1]?.click()
    }, 400)
  }
  if (params.get('dialog') === 'delete') {
    window.setTimeout(() => {
      document.querySelector('button[title="删除"]')?.click()
    }, 600)
  }
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
