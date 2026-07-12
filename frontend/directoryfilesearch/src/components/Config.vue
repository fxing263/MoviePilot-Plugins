<template>
  <div class="file-search-config">
    <header class="config-header">
      <div>
        <div class="text-h6">目录文件搜索删除</div>
        <div class="config-subtitle">插件设置</div>
      </div>
      <v-btn icon="mdi-close" variant="text" size="small" title="关闭" @click="emit('close')" />
    </header>

    <v-divider />

    <main class="config-content">
      <section class="config-section">
        <div class="section-title">
          <v-icon icon="mdi-power" color="success" size="19" />
          <span>运行</span>
        </div>
        <v-switch
          v-model="config.enabled"
          color="success"
          label="启用插件"
          hide-details
          inset
        />
      </section>

      <v-divider />

      <section class="config-section directory-section">
        <div class="section-title">
          <v-icon icon="mdi-folder-search-outline" color="primary" size="19" />
          <span>搜索目录</span>
        </div>
        <v-text-field
          v-model="config.root_dir"
          label="目录绝对路径"
          prepend-inner-icon="mdi-folder-outline"
          variant="outlined"
          :error-messages="rootError"
          hide-details="auto"
        />
      </section>
    </main>

    <footer class="config-actions">
      <v-btn variant="text" @click="emit('close')">取消</v-btn>
      <v-btn
        color="primary"
        prepend-icon="mdi-content-save"
        :disabled="saveDisabled"
        @click="saveConfig"
      >
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
const config = reactive({ enabled: false, root_dir: '' })

const rootError = computed(() => (
  config.enabled && !String(config.root_dir || '').trim()
    ? ['启用插件后必须配置目录']
    : []
))
const saveDisabled = computed(() => rootError.value.length > 0)

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

const replaceConfig = (value) => {
  config.enabled = normalizeBoolean(value?.enabled, false)
  config.root_dir = String(value?.root_dir || '')
}

const saveConfig = () => {
  emit('save', {
    enabled: Boolean(config.enabled),
    root_dir: String(config.root_dir || '').trim(),
  })
}

watch(
  () => props.initialConfig,
  (value) => replaceConfig(value || {}),
  { deep: true, immediate: true },
)
</script>

<style scoped>
.file-search-config {
  --dfs-surface: #ffffff;
  --dfs-text: #1f2937;
  --dfs-muted: #4b5563;
  --dfs-border: #d1d5db;
  --dfs-accent: #2563eb;
  --dfs-success: #15803d;
  --dfs-disabled-bg: #e5e7eb;
  --dfs-disabled-text: #374151;
  --dfs-on-accent: #ffffff;
  --v-theme-surface: 255, 255, 255;
  --v-theme-on-surface: 31, 41, 55;
  --v-theme-on-surface-variant: 75, 85, 99;
  --v-theme-primary: 37, 99, 235;
  --v-theme-on-primary: 255, 255, 255;
  --v-theme-success: 21, 128, 61;
  --v-theme-on-success: 255, 255, 255;
  --v-border-color: 107, 114, 128;
  --v-border-opacity: 0.38;
  --v-high-emphasis-opacity: 1;
  --v-medium-emphasis-opacity: 1;
  --v-disabled-opacity: 1;
  display: flex;
  height: min(560px, 88vh);
  min-height: 420px;
  flex-direction: column;
  background: var(--dfs-surface);
  color: var(--dfs-text);
  color-scheme: light;
  letter-spacing: 0;
}

:global(.v-theme--dark .file-search-config),
:global(.file-search-config.v-theme--dark) {
  --dfs-surface: #111827;
  --dfs-text: #f3f4f6;
  --dfs-muted: #cbd5e1;
  --dfs-border: #475569;
  --dfs-accent: #60a5fa;
  --dfs-success: #4ade80;
  --dfs-disabled-bg: #273449;
  --dfs-disabled-text: #cbd5e1;
  --dfs-on-accent: #0f172a;
  --v-theme-surface: 17, 24, 39;
  --v-theme-on-surface: 243, 244, 246;
  --v-theme-on-surface-variant: 203, 213, 225;
  --v-theme-primary: 96, 165, 250;
  --v-theme-on-primary: 15, 23, 42;
  --v-theme-success: 74, 222, 128;
  --v-theme-on-success: 15, 23, 42;
  --v-border-color: 148, 163, 184;
  --v-border-opacity: 0.38;
  color-scheme: dark;
}

.file-search-config :deep(.v-label),
.config-subtitle {
  color: var(--dfs-muted) !important;
  opacity: 1 !important;
}

.file-search-config :deep(.v-field__input),
.file-search-config :deep(.v-selection-control__label) {
  color: var(--dfs-text);
  opacity: 1;
}

.file-search-config :deep(.v-field__outline) {
  color: var(--dfs-border);
  opacity: 1;
}

.file-search-config :deep(.text-primary) { color: var(--dfs-accent) !important; }
.file-search-config :deep(.text-success) { color: var(--dfs-success) !important; }
.file-search-config :deep(.bg-primary) {
  background: var(--dfs-accent) !important;
  color: var(--dfs-on-accent) !important;
}

.file-search-config :deep(.v-divider) {
  border-color: var(--dfs-border) !important;
  opacity: 1;
}

.file-search-config :deep(.v-btn--disabled) {
  border-color: var(--dfs-border) !important;
  background: var(--dfs-disabled-bg) !important;
  color: var(--dfs-disabled-text) !important;
  opacity: 1 !important;
}

.config-header,
.config-actions,
.section-title {
  display: flex;
  align-items: center;
}

.config-header {
  justify-content: space-between;
  gap: 16px;
  padding: 18px 22px;
}

.config-subtitle {
  margin-top: 2px;
  font-size: 0.76rem;
}

.config-content {
  flex: 1 1 auto;
  overflow-y: auto;
}

.config-section {
  padding: 22px;
}

.directory-section {
  padding-bottom: 28px;
}

.section-title {
  gap: 8px;
  margin-bottom: 16px;
  font-size: 0.9rem;
  font-weight: 650;
}

.config-actions {
  justify-content: flex-end;
  gap: 8px;
  padding: 13px 22px;
  border-top: 1px solid var(--dfs-border);
}

@media (max-width: 700px) {
  .file-search-config {
    height: 100vh;
    min-height: 0;
  }

  .config-header,
  .config-section,
  .config-actions {
    padding-right: 16px;
    padding-left: 16px;
  }
}
</style>
