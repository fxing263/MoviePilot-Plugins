<template>
  <div class="plugin-config config-page">
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
        aria-label="关闭插件设置"
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
            :error-messages="sourceError"
            hide-details="auto"
          />
          <v-text-field
            v-model="config.target_dir"
            label="目标目录"
            prepend-inner-icon="mdi-folder-arrow-left-right-outline"
            variant="outlined"
            :error-messages="targetError"
            hide-details="auto"
          />
        </div>
        <p class="field-help">源目录用于读取 9kg 元数据，目标目录用于番号系列镜像；启用插件后两者都必须配置。</p>
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
        <p class="field-help">每行填写一个允许的网盘挂载根目录，删除预览不会接受越界路径。</p>
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
        <p class="field-help">扩展名可直接输入，保存时会统一为小写并自动补全开头的点号。</p>
      </section>
    </main>

    <footer class="config-actions">
      <v-btn variant="text" @click="emit('close')">取消</v-btn>
      <v-btn color="primary" prepend-icon="mdi-content-save" :disabled="saveDisabled" @click="saveConfig">
        保存
      </v-btn>
    </footer>
  </div>
</template>

<script setup>
import { computed, reactive, watch } from 'vue'

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
const sourceError = computed(() => (
  config.enabled && !String(config.source_dir || '').trim()
    ? ['启用插件后必须配置源目录']
    : []
))
const targetError = computed(() => (
  config.enabled && !String(config.target_dir || '').trim()
    ? ['启用插件后必须配置目标目录']
    : []
))
const saveDisabled = computed(() => sourceError.value.length > 0 || targetError.value.length > 0)

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
.plugin-config {
  --mms-surface: rgb(var(--v-theme-surface));
  --mms-text: rgb(var(--v-theme-on-surface));
  --mms-muted: rgb(var(--v-theme-on-surface-variant));
  --mms-border: rgba(var(--v-border-color), var(--v-border-opacity));
  --mms-disabled-bg: rgba(var(--v-theme-on-surface), 0.12);
  --mms-disabled-text: rgba(var(--v-theme-on-surface), 0.68);
  --mms-accent: rgb(var(--v-theme-primary));
  --mms-secondary: rgb(var(--v-theme-secondary));
  --mms-success: rgb(var(--v-theme-success));
  --mms-warning: rgb(var(--v-theme-warning));
  --mms-danger: rgb(var(--v-theme-error));
  --mms-info: rgb(var(--v-theme-info));
  --mms-warning-soft: rgba(var(--v-theme-warning), 0.12);
  --mms-on-accent: rgb(var(--v-theme-on-primary));
  display: flex;
  min-height: min(560px, 88vh);
  max-height: 92vh;
  flex-direction: column;
  overflow: hidden;
  background: var(--mms-surface);
  color: var(--mms-text);
  letter-spacing: 0;
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

.config-header :deep(.v-btn),
.config-actions :deep(.v-btn) {
  min-height: 44px;
}

.field-help {
  margin: 8px 0 0;
  color: rgba(var(--v-theme-on-surface), 0.72);
  font-size: 0.8125rem;
  line-height: 1.5;
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
  .plugin-config {
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

@media (prefers-reduced-motion: reduce) {
  .plugin-config *,
  .plugin-config *::before,
  .plugin-config *::after {
    transition-duration: 0.01ms !important;
    animation-duration: 0.01ms !important;
  }
}
</style>
