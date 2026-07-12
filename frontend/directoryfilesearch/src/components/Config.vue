<template>
  <div class="plugin-config file-search-config">
    <header class="config-header">
      <div>
        <div class="text-h6">目录文件搜索删除</div>
        <div class="config-subtitle">插件设置</div>
      </div>
      <v-btn icon="mdi-close" variant="text" size="small" title="关闭" aria-label="关闭插件设置" @click="emit('close')" />
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
        <p class="field-help">填写要递归搜索的绝对目录。页面只展示该目录内的普通文件，删除前仍会校验路径和文件快照。</p>
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
.plugin-config {
  --dfs-surface: rgb(var(--v-theme-surface));
  --dfs-text: rgb(var(--v-theme-on-surface));
  --dfs-muted: rgb(var(--v-theme-on-surface-variant));
  --dfs-border: rgba(var(--v-border-color), var(--v-border-opacity));
  --dfs-accent: rgb(var(--v-theme-primary));
  --dfs-success: rgb(var(--v-theme-success));
  --dfs-disabled-bg: rgba(var(--v-theme-on-surface), 0.12);
  --dfs-disabled-text: rgba(var(--v-theme-on-surface), 0.68);
  --dfs-on-accent: rgb(var(--v-theme-on-primary));
  display: flex;
  min-height: min(560px, 88vh);
  max-height: 92vh;
  flex-direction: column;
  overflow: hidden;
  background: var(--dfs-surface);
  color: var(--dfs-text);
  letter-spacing: 0;
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

@media (max-width: 700px) {
  .plugin-config {
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

@media (prefers-reduced-motion: reduce) {
  .plugin-config *,
  .plugin-config *::before,
  .plugin-config *::after {
    transition-duration: 0.01ms !important;
    animation-duration: 0.01ms !important;
  }
}
</style>
