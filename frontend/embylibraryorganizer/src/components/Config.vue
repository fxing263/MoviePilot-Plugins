<template>
  <div class="plugin-config config-page">
    <header class="config-header">
      <div>
        <div class="text-h6">Emby媒体库整理</div>
        <div class="text-caption text-medium-emphasis">插件设置</div>
      </div>
      <v-btn icon="mdi-close" variant="text" size="small" title="关闭" aria-label="关闭插件设置" @click="emit('close')" />
    </header>

    <v-divider />

    <main class="config-content">
      <section class="config-section">
        <div class="section-title">运行</div>
        <v-switch
          v-model="config.enabled"
          color="success"
          label="启用插件"
          hide-details
          inset
        />
      </section>

      <v-divider />

      <section class="config-section">
        <div class="section-title">媒体库路径</div>
        <div class="field-grid">
          <v-textarea
            v-model="config.library_paths"
            label="混合媒体库"
            rows="2"
            auto-grow
            variant="outlined"
            :error-messages="libraryPathError"
          />
          <v-textarea v-model="config.bluray_library_paths" label="蓝光媒体库" rows="2" auto-grow variant="outlined" />
        </div>
        <p class="field-help">每行填写一个绝对路径。混合媒体库会识别电影、电视剧和动漫二级分类；蓝光媒体库统一归入“蓝光”。</p>
        <div class="subsection-title">分类识别文件夹名</div>
        <div class="field-grid">
          <v-textarea v-model="config.movie_category_root_names" label="电影文件夹名" rows="2" auto-grow variant="outlined" />
          <v-textarea v-model="config.tv_category_root_names" label="电视剧文件夹名" rows="2" auto-grow variant="outlined" />
          <v-textarea v-model="config.anime_category_root_names" label="动漫文件夹名" rows="2" auto-grow variant="outlined" />
        </div>
      </section>

      <v-divider />

      <section class="config-section">
        <div class="section-title-row">
          <div class="section-title">专项扫描分类</div>
          <div class="section-actions">
            <v-progress-circular v-if="categoriesLoading" indeterminate size="18" width="2" />
            <v-btn
              icon="mdi-folder-search-outline"
              variant="text"
              size="small"
              title="按当前路径和文件夹名重新识别"
              :disabled="categoriesLoading"
              @click="loadCategories"
            />
          </div>
        </div>
        <div class="category-grid">
          <v-select
            :model-value="config.orphan_metadata_categories"
            :items="categories"
            item-title="title"
            item-value="value"
            label="多余元数据分类"
            variant="outlined"
            multiple
            chips
            closable-chips
            :loading="categoriesLoading"
            no-data-text="未识别到分类"
            @update:model-value="updateCategorySelection('orphan_metadata_categories', $event)"
          />
          <v-select
            :model-value="config.missing_metadata_categories"
            :items="categories"
            item-title="title"
            item-value="value"
            label="缺失元数据分类"
            variant="outlined"
            multiple
            chips
            closable-chips
            :loading="categoriesLoading"
            no-data-text="未识别到分类"
            @update:model-value="updateCategorySelection('missing_metadata_categories', $event)"
          />
        </div>
        <p class="field-help">页面专项扫描会使用这里保存的分类；“全部（全量）”与具体分类不能同时选择。</p>
      </section>

      <v-divider />

      <section class="config-section">
        <div class="section-title">删除与复核</div>
        <div class="field-grid compact-grid">
          <v-textarea
            v-model="config.cd2_mount_paths"
            label="CD2挂载根目录"
            rows="2"
            auto-grow
            variant="outlined"
          />
          <v-text-field
            v-model.number="config.max_delete_count"
            label="单次最大STRM数量"
            type="number"
            min="1"
            variant="outlined"
          />
        </div>
        <p class="field-help">CD2 源文件必须位于允许的挂载根目录内，删除仍需经过预览、确认和复核。</p>
      </section>
    </main>

    <footer class="config-actions">
      <v-btn variant="text" @click="emit('close')">取消</v-btn>
      <v-btn color="primary" prepend-icon="mdi-content-save" :disabled="saveDisabled" @click="saveConfig">保存</v-btn>
    </footer>

    <v-snackbar v-model="snackbar.show" :color="snackbar.color" timeout="3500">
      {{ snackbar.text }}
    </v-snackbar>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'

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

const emit = defineEmits(['save', 'close', 'switch'])
const pluginId = EMBY_LIBRARY_ORGANIZER_PLUGIN_ID
const ALL_CATEGORIES_VALUE = '__all__'
const categories = ref([])
const categoriesLoading = ref(false)
const config = reactive({})
const snackbar = reactive({ show: false, text: '', color: 'error' })
const libraryPathError = computed(() => (
  config.enabled
  && !String(config.library_paths || '').trim()
  && !String(config.bluray_library_paths || '').trim()
    ? ['启用插件后至少配置一个媒体库路径']
    : []
))
const saveDisabled = computed(() => libraryPathError.value.length > 0)

const replaceConfig = (value) => {
  for (const key of Object.keys(config)) delete config[key]
  Object.assign(config, JSON.parse(JSON.stringify(value || {})))
  if (!Array.isArray(config.missing_metadata_categories)) {
    config.missing_metadata_categories = []
  }
  if (!Array.isArray(config.orphan_metadata_categories)) {
    config.orphan_metadata_categories = []
  }
  delete config.movie_library_paths
  delete config.tv_library_paths
  delete config.anime_library_paths
  if (config.bluray_library_paths === undefined) config.bluray_library_paths = ''
  if (config.movie_category_root_names === undefined) config.movie_category_root_names = '电影'
  if (config.tv_category_root_names === undefined) config.tv_category_root_names = '电视剧\n剧集'
  if (config.anime_category_root_names === undefined) config.anime_category_root_names = '动漫'
  if (config.cd2_mount_paths === undefined) config.cd2_mount_paths = '/CloudNAS/CloudDrive'
  if (config.max_delete_count === undefined) config.max_delete_count = 20
}

const loadCategories = async () => {
  categoriesLoading.value = true
  try {
    const query = new URLSearchParams({
      config_json: JSON.stringify(config),
    })
    const result = await props.api.post(
      `plugin/${pluginId}/categories/preview?${query.toString()}`,
    )
    if (!result || result.code !== 0) throw new Error(result?.msg || '分类加载失败')
    categories.value = result.data || []
    const availableValues = new Set(categories.value.map((item) => item.value))
    config.orphan_metadata_categories = config.orphan_metadata_categories.filter(
      (value) => availableValues.has(value),
    )
    config.missing_metadata_categories = config.missing_metadata_categories.filter(
      (value) => availableValues.has(value),
    )
  } catch (error) {
    snackbar.text = error?.message || '分类加载失败'
    snackbar.color = 'error'
    snackbar.show = true
  } finally {
    categoriesLoading.value = false
  }
}

const saveConfig = () => {
  emit('save', JSON.parse(JSON.stringify(config)))
}

const updateCategorySelection = (key, values) => {
  const previous = Array.isArray(config[key]) ? config[key] : []
  const valuesList = Array.isArray(values) ? [...values] : []
  if (!valuesList.includes(ALL_CATEGORIES_VALUE)) {
    config[key] = valuesList
    return
  }
  config[key] = previous.includes(ALL_CATEGORIES_VALUE)
    ? valuesList.filter((value) => value !== ALL_CATEGORIES_VALUE)
    : [ALL_CATEGORIES_VALUE]
}

watch(
  () => props.initialConfig,
  (value) => replaceConfig(value),
  { deep: true, immediate: true },
)

onMounted(loadCategories)
</script>

<style scoped>
.plugin-config {
  --config-muted: rgba(var(--v-theme-on-surface), 0.72);
  display: flex;
  min-height: min(560px, 88vh);
  max-height: 92vh;
  flex-direction: column;
  overflow: hidden;
  background: rgb(var(--v-theme-surface));
  color: rgb(var(--v-theme-on-surface));
  letter-spacing: 0;
}

.plugin-config :deep(.text-medium-emphasis) {
  color: var(--config-muted) !important;
  opacity: 1 !important;
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
  min-width: 44px;
  min-height: 44px;
}

.field-help {
  margin: 8px 0 0;
  color: rgba(var(--v-theme-on-surface), 0.72);
  font-size: 0.8125rem;
  line-height: 1.5;
}

.config-content {
  flex: 1;
  overflow-y: auto;
}

.config-section {
  padding: 20px 22px;
}

.section-title,
.section-title-row {
  margin-bottom: 14px;
  font-size: 0.9rem;
  font-weight: 600;
}

.section-title-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.section-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.subsection-title {
  margin: 12px 0 14px;
  color: var(--config-muted);
  font-size: 0.8rem;
  font-weight: 600;
}

.field-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 4px 16px;
}

.category-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
}

.compact-grid {
  grid-template-columns: minmax(0, 2fr) minmax(180px, 1fr);
}

.config-actions {
  justify-content: flex-end;
  border-top: 1px solid rgba(var(--v-border-color), var(--v-border-opacity));
}

@media (max-width: 700px) {
  .plugin-config {
    height: 100vh;
    min-height: 0;
  }

  .field-grid,
  .category-grid,
  .compact-grid {
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
