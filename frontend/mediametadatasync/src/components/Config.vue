<template>
  <div class="config-page">
    <header class="config-header">
      <div class="header-copy">
        <div class="text-h6">媒体元数据双目录同步</div>
        <div class="text-caption text-medium-emphasis">插件设置</div>
      </div>
      <v-btn
        icon="mdi-close"
        variant="text"
        size="small"
        title="关闭"
        @click="emit('close')"
      />
    </header>

    <v-divider />

    <main class="config-content">
      <section class="config-section">
        <div class="section-title">
          <v-icon icon="mdi-power" size="19" color="success" />
          <span>运行</span>
        </div>
        <div class="switch-grid">
          <v-switch
            v-model="config.enabled"
            color="success"
            label="启用插件"
            hide-details
            inset
          />
          <v-switch
            v-model="config.monitor_enabled"
            color="info"
            label="启用实时监控"
            hide-details
            inset
          />
          <v-switch
            v-model="config.reverse_sync_enabled"
            color="secondary"
            label="启用 JSON 实时回写"
            hide-details
            inset
          />
        </div>
      </section>

      <v-divider />

      <section class="config-section">
        <div class="section-title">
          <v-icon icon="mdi-folder-arrow-left-right-outline" size="19" color="primary" />
          <span>同步目录</span>
        </div>
        <div class="path-fields">
          <v-text-field
            v-model="config.source_dir"
            label="源目录"
            prepend-inner-icon="mdi-folder-arrow-right-outline"
            variant="outlined"
            hide-details="auto"
          />
          <v-text-field
            v-model="config.target_dir"
            label="目标目录"
            prepend-inner-icon="mdi-folder-arrow-left-right-outline"
            variant="outlined"
            hide-details="auto"
          />
        </div>
      </section>

      <v-divider />

      <section class="config-section">
        <div class="section-title">
          <v-icon icon="mdi-shield-check-outline" size="19" color="warning" />
          <span>删除边界</span>
        </div>
        <div class="delete-grid">
          <v-textarea
            v-model="config.cloud_mount_paths"
            label="网盘挂载根目录"
            prepend-inner-icon="mdi-cloud-outline"
            variant="outlined"
            rows="2"
            auto-grow
            hide-details="auto"
          />
          <v-text-field
            v-model.number="config.max_delete_files"
            label="单条最大删除文件数"
            type="number"
            min="1"
            max="500"
            step="1"
            prepend-inner-icon="mdi-counter"
            variant="outlined"
            hide-details="auto"
          />
        </div>
        <v-alert type="warning" variant="tonal" density="compact" class="delete-alert">
          网盘路径必须位于上述挂载根目录；三端删除始终需要预览和二次确认。
        </v-alert>
      </section>

      <v-divider />

      <section class="config-section">
        <div class="section-title">
          <v-icon icon="mdi-tune-variant" size="19" color="secondary" />
          <span>同步规则</span>
        </div>
        <div class="rule-grid">
          <v-text-field
            v-model="config.other_category"
            label="非 A-Z 分类名"
            prepend-inner-icon="mdi-folder-pound-outline"
            variant="outlined"
            hide-details="auto"
          />
          <v-text-field
            v-model.number="config.settle_seconds"
            label="目录稳定等待"
            type="number"
            min="1"
            step="1"
            suffix="秒"
            prepend-inner-icon="mdi-timer-sand"
            variant="outlined"
            hide-details="auto"
          />
        </div>
        <v-combobox
          v-model="config.sync_extensions"
          :items="extensionOptions"
          label="正向同步扩展名"
          prepend-inner-icon="mdi-file-multiple-outline"
          variant="outlined"
          multiple
          chips
          closable-chips
          clearable
          hide-details="auto"
          class="extension-field"
        />
      </section>
    </main>

    <footer class="config-actions">
      <v-btn variant="text" @click="emit('close')">取消</v-btn>
      <v-btn color="primary" prepend-icon="mdi-content-save" @click="saveConfig">
        保存
      </v-btn>
    </footer>
  </div>
</template>

<script setup>
import { reactive, watch } from 'vue'

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

const emit = defineEmits(['save', 'close', 'switch'])
const defaultExtensions = [
  '.strm',
  '.nfo',
  '.jpg',
  '.jpeg',
  '.png',
  '.webp',
  '.gif',
  '.json',
]
const extensionOptions = [...defaultExtensions]
const config = reactive({})

const normalizeBoolean = (value, fallback) => {
  if (typeof value === 'boolean') return value
  if (typeof value === 'number') return value !== 0
  if (typeof value === 'string') {
    const normalized = value.trim().toLowerCase()
    if (['true', '1', 'yes', 'on'].includes(normalized)) return true
    if (['false', '0', 'no', 'off', ''].includes(normalized)) return false
  }
  return fallback
}

const normalizeExtensions = (value) => {
  const values = Array.isArray(value)
    ? value
    : String(value || '').split(/[\s,;]+/)
  return [...new Set(values
    .map((item) => String(item || '').trim().toLowerCase())
    .filter(Boolean)
    .map((item) => (item.startsWith('.') ? item : `.${item}`)))]
}

const replaceConfig = (value) => {
  const nextConfig = {
    enabled: false,
    monitor_enabled: true,
    reverse_sync_enabled: true,
    source_dir: '/media/9kg',
    target_dir: '/media/番号系列',
    other_category: '其他',
    settle_seconds: 2,
    sync_extensions: [...defaultExtensions],
    cloud_mount_paths: '/CloudNAS/CloudDrive',
    max_delete_files: 100,
    ...(value || {}),
  }
  nextConfig.enabled = normalizeBoolean(nextConfig.enabled, false)
  nextConfig.monitor_enabled = normalizeBoolean(nextConfig.monitor_enabled, true)
  nextConfig.reverse_sync_enabled = normalizeBoolean(nextConfig.reverse_sync_enabled, true)
  nextConfig.source_dir = String(nextConfig.source_dir || '')
  nextConfig.target_dir = String(nextConfig.target_dir || '')
  nextConfig.other_category = String(nextConfig.other_category || '其他')
  nextConfig.settle_seconds = Number(nextConfig.settle_seconds ?? 2)
  nextConfig.sync_extensions = normalizeExtensions(nextConfig.sync_extensions)
  nextConfig.cloud_mount_paths = Array.isArray(nextConfig.cloud_mount_paths)
    ? nextConfig.cloud_mount_paths.join('\n')
    : String(nextConfig.cloud_mount_paths || '')
  nextConfig.max_delete_files = Number(nextConfig.max_delete_files ?? 100)

  for (const key of Object.keys(config)) delete config[key]
  Object.assign(config, nextConfig)
}

const saveConfig = () => {
  const nextConfig = JSON.parse(JSON.stringify(config))
  nextConfig.settle_seconds = Math.max(1, Math.trunc(Number(nextConfig.settle_seconds) || 1))
  nextConfig.sync_extensions = normalizeExtensions(nextConfig.sync_extensions)
  nextConfig.cloud_mount_paths = String(nextConfig.cloud_mount_paths || '')
    .split(/\r?\n/)
    .map((item) => item.trim())
    .filter(Boolean)
  nextConfig.max_delete_files = Math.min(
    500,
    Math.max(1, Math.trunc(Number(nextConfig.max_delete_files) || 100)),
  )
  emit('save', nextConfig)
}

watch(
  () => props.initialConfig,
  (value) => replaceConfig(value),
  { deep: true, immediate: true },
)
</script>

<style scoped>
.config-page {
  --mms-surface: #ffffff;
  --mms-text: #1f2937;
  --mms-muted: #4b5563;
  --mms-border: #d1d5db;
  --mms-disabled-bg: #e5e7eb;
  --mms-disabled-text: #374151;
  --mms-accent: #2563eb;
  --mms-secondary: #0f766e;
  --mms-success: #15803d;
  --mms-warning: #a16207;
  --mms-danger: #b91c1c;
  --mms-info: #0369a1;
  --mms-warning-soft: #fffbeb;
  --mms-on-accent: #ffffff;
  --v-theme-surface: 255, 255, 255;
  --v-theme-surface-variant: 243, 244, 246;
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
  display: flex;
  height: min(720px, 90vh);
  min-height: 540px;
  flex-direction: column;
  background: var(--mms-surface);
  color: var(--mms-text);
  color-scheme: light;
  letter-spacing: 0;
}

:global(.v-theme--dark .config-page),
:global(.config-page.v-theme--dark) {
  --mms-surface: #111827;
  --mms-text: #f3f4f6;
  --mms-muted: #cbd5e1;
  --mms-border: #475569;
  --mms-disabled-bg: #273449;
  --mms-disabled-text: #cbd5e1;
  --mms-accent: #60a5fa;
  --mms-secondary: #5eead4;
  --mms-success: #4ade80;
  --mms-warning: #fbbf24;
  --mms-danger: #f87171;
  --mms-info: #38bdf8;
  --mms-warning-soft: #422006;
  --mms-on-accent: #0f172a;
  --v-theme-surface: 17, 24, 39;
  --v-theme-surface-variant: 31, 41, 55;
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

.config-page :deep(.text-medium-emphasis),
.config-page :deep(.v-label) {
  color: var(--mms-muted) !important;
  opacity: 1 !important;
}

.config-page :deep(.v-field__input),
.config-page :deep(.v-selection-control__label) {
  color: var(--mms-text);
  opacity: 1;
}

.config-page :deep(.v-field__outline) {
  color: var(--mms-border);
  opacity: 1;
}

.config-page :deep(.text-primary) { color: var(--mms-accent) !important; }
.config-page :deep(.text-secondary) { color: var(--mms-secondary) !important; }
.config-page :deep(.text-success) { color: var(--mms-success) !important; }
.config-page :deep(.text-warning) { color: var(--mms-warning) !important; }
.config-page :deep(.text-error) { color: var(--mms-danger) !important; }
.config-page :deep(.text-info) { color: var(--mms-info) !important; }

.config-page :deep(.bg-primary) {
  background-color: var(--mms-accent) !important;
  color: var(--mms-on-accent) !important;
}

.config-page :deep(.v-divider) {
  border-color: var(--mms-border) !important;
  opacity: 1;
}

.config-page :deep(.v-btn--disabled) {
  border-color: var(--mms-border) !important;
  background: var(--mms-disabled-bg) !important;
  color: var(--mms-disabled-text) !important;
  box-shadow: none !important;
  opacity: 1 !important;
}

.config-page :deep(.v-btn--disabled .v-btn__overlay) {
  opacity: 0 !important;
}

.config-header,
.config-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 18px 22px;
}

.header-copy {
  min-width: 0;
}

.config-content {
  flex: 1 1 auto;
  overflow-y: auto;
}

.config-section {
  padding: 20px 22px;
}

.section-title {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 16px;
  font-size: 0.9rem;
  font-weight: 600;
}

.switch-grid,
.path-fields,
.rule-grid,
.delete-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
}

.switch-grid {
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px 24px;
}

.extension-field {
  margin-top: 18px;
}

.delete-grid {
  grid-template-columns: minmax(0, 1.5fr) minmax(220px, 0.5fr);
  align-items: start;
}

.delete-alert {
  margin-top: 14px;
  background: var(--mms-warning-soft) !important;
  color: var(--mms-warning) !important;
}

.delete-alert :deep(.v-alert__underlay) {
  opacity: 0 !important;
}

.config-actions {
  justify-content: flex-end;
  border-top: 1px solid var(--mms-border);
}

@media (max-width: 760px) {
  .config-page {
    height: 100vh;
    min-height: 0;
  }

  .switch-grid,
  .path-fields,
  .rule-grid,
  .delete-grid {
    grid-template-columns: minmax(0, 1fr);
  }

  .config-header,
  .config-section,
  .config-actions {
    padding-right: 16px;
    padding-left: 16px;
  }
}
</style>
