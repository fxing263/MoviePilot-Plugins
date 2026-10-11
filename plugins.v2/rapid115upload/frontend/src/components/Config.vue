<template>
  <div class="upload-config">
    <header class="config-header">
      <div class="config-title">媒体整理增强</div>
      <p class="config-subtitle">本地整理完成后，按目录映射上传115</p>
    </header>
    <v-tabs v-model="tab" color="primary" density="compact" class="config-tabs" grow>
      <v-tab value="general">基本设置</v-tab>
      <v-tab value="mappings">目录映射 · {{ config.mappings.length }}</v-tab>
      <v-tab value="qb">qB 标签</v-tab><v-tab value="bdmv">BDMV 上传</v-tab>
    </v-tabs>
    <v-progress-linear v-if="loading" indeterminate />
    <v-alert v-if="error" type="error" variant="tonal" density="compact" class="config-error">{{ error }}</v-alert>
    <fieldset :disabled="loading || saving || loadFailed" class="config-body">
      <section v-show="tab === 'general'" aria-label="基本设置" class="config-panel">
        <div class="switch-row">
          <div><strong>启用插件</strong><p>接收新的整理事件，并处理上传队列</p></div>
          <v-switch v-model="config.enabled" aria-label="启用插件" color="primary" density="compact" hide-details />
        </div>
        <div class="field-grid">
          <div class="config-field">
            <label class="field-label" for="rapid-concurrency">同时处理数</label>
            <v-text-field id="rapid-concurrency" v-model.number="config.concurrency" aria-label="同时处理数" type="number" min="1" max="16" variant="outlined" density="compact" hide-details />
            <p class="field-help">默认2个，等待重试不占用名额。</p>
          </div>
        </div>
        <div class="config-field">
          <label class="field-label" for="rapid-after-upload">上传完成后处理</label>
          <v-select id="rapid-after-upload" v-model="afterUpload" :items="[{ title: '保留硬链接文件', value: 'keep' }, { title: '删除硬链接文件', value: 'delete' }, { title: '删除硬链接文件及空的父文件夹', value: 'delete_empty' }]" aria-label="上传完成后处理" variant="outlined" density="compact" hide-details />
          <p class="field-help">仅在115上传成功后删除。清理空父文件夹时遇到非空目录即停止，保留整理根目录。</p>
        </div>
        <div class="config-note">先在 MP 存储设置中授权115。停用插件会暂停队列。</div>
      </section>

      <section v-show="tab === 'mappings'" aria-label="目录映射" class="config-panel">
        <v-alert v-if="directoryError" type="error" variant="tonal" density="compact">{{ directoryError }} <v-btn variant="text" size="small" @click="loadDirectories">重新读取</v-btn></v-alert>
        <p v-else-if="!loading && !directories.length" class="field-help">没有可用的本地整理目标，请先在 MP 设置 → 目录管理中配置本地媒体库目录。</p>
        <div class="mapping-toolbar">
          <v-select v-if="config.mappings.length" v-model="mappingIndex" :items="mappingOptions" aria-label="选择目录映射" variant="outlined" density="compact" hide-details class="mapping-select" />
          <span v-else class="field-help">尚未配置目录映射</span>
          <v-btn variant="tonal" color="primary" size="small" @click="addMapping">添加映射</v-btn>
        </div>
        <template v-if="mapping">
          <div class="config-field">
            <label class="field-label" for="rapid-local">MP整理目标目录</label>
            <v-select id="rapid-local" v-model="mapping.library_root" :items="directories" aria-label="MP整理目标目录" placeholder="选择目录管理中的本地媒体库" variant="outlined" density="compact" hide-details />
            <p v-if="mapping.library_root && !directories.some(item => item.value === mapping.library_root)" class="field-help text-error">该目录已不在系统目录管理中，请重新选择。</p>
            <p class="field-help">来自 MP 设置 → 目录管理，使用“媒体库目录”，不是下载目录。</p>
          </div>
          <div class="config-field">
            <label class="field-label" for="rapid-remote">115目标根目录</label>
            <v-text-field id="rapid-remote" v-model="mapping.remote_root" aria-label="115目标根目录" placeholder="/影视库/电影" variant="outlined" density="compact" hide-details />
            <p class="field-help">填写网盘路径，子目录与文件名原样保留。</p>
          </div>
          <div class="config-field">
            <label class="field-label" for="rapid-attempts">最大秒传尝试次数</label>
            <v-text-field id="rapid-attempts" v-model.number="mapping.max_attempts" aria-label="最大秒传尝试次数" type="number" min="1" max="1000" variant="outlined" density="compact" hide-details />
            <p class="field-help">仅对本目录生效，默认3次；明确未命中达到上限后普通上传，网络异常不消耗次数。</p>
          </div>
          <div class="config-field">
            <label class="field-label" for="rapid-initial-delay">首次上传前等待（第0次） <span class="field-unit">分钟</span></label>
            <v-text-field id="rapid-initial-delay" v-model.number="mapping.initial_delay_minutes" aria-label="首次上传前等待分钟数" type="number" min="0" max="525600" variant="outlined" density="compact" hide-details />
            <p class="field-help">默认0，入队后立即尝试。首次等待不占并发名额，不计入尝试次数；仅影响新入队文件。</p>
          </div>
          <div class="config-field">
            <div class="field-label">失败后的等待时间 <span class="field-unit">分钟</span></div>
            <div class="retry-grid">
              <div v-for="(_, tier) in mapping.retry_minutes" :key="tier" class="retry-field">
                <label class="field-help" :for="`rapid-retry-${tier}`">第 {{ tier + 1 }} 次失败后</label>
                <div class="retry-input">
                  <v-text-field :id="`rapid-retry-${tier}`" v-model.number="mapping.retry_minutes[tier]" :aria-label="`第${tier + 1}次失败后等待分钟数`" type="number" min="1" max="525600" variant="outlined" density="compact" hide-details />
                  <v-btn icon="mdi-close" variant="text" size="x-small" :aria-label="`删除第${tier + 1}个等待阶段`" :disabled="mapping.retry_minutes.length <= 1" @click="mapping.retry_minutes.splice(tier, 1)" />
                </div>
              </div>
            </div>
            <v-btn class="add-retry" variant="text" size="small" color="primary" @click="mapping.retry_minutes.push(1440)">＋ 添加等待阶段</v-btn>
          </div>
          <div class="mapping-bottom">
            <p class="field-help">网络异常按末档间隔重试，秒传未命中达到上限后普通上传。</p>
            <v-btn color="error" variant="text" size="small" @click="removeMapping">删除此映射</v-btn>
          </div>
        </template>
        <div v-else class="empty-mappings">添加一组本地目录与115目录，只有匹配的整理文件才会入队。</div>
      </section>

      <section v-show="tab === 'qb'" aria-label="qB标签设置" class="config-panel">
        <div class="switch-row">
          <div><strong>下载器监控增强</strong><p>继续使用 MP 原有的下载器监控与整理流程</p></div>
          <v-switch v-model="config.qb_enabled" aria-label="下载器监控增强" color="primary" density="compact" hide-details />
        </div>
        <v-alert v-if="downloaderError" type="error" variant="tonal" density="compact">{{ downloaderError }} <v-btn variant="text" size="small" @click="loadDownloaders">重新读取</v-btn></v-alert>
        <p v-else-if="!loading && !downloaders.length" class="field-help">没有可用的 qB 下载器，请先在 MP 设置中添加并启用。</p>
        <div class="config-field">
          <label class="field-label" for="rapid-downloaders">监控的qB下载器</label>
          <v-select id="rapid-downloaders" v-model="config.downloaders" :items="downloaders" aria-label="监控的qB下载器" multiple chips closable-chips clearable placeholder="选择已有下载器，可多选" variant="outlined" density="compact" hide-details />
          <p class="field-help">来自 MP 已启用的 qB 下载器。选择后只监控所选 qB；留空为全部。</p>
        </div>
        <div class="field-grid">
          <div class="config-field">
            <label class="field-label" for="rapid-include">标签白名单</label>
            <v-combobox id="rapid-include" v-model="config.include_tags" aria-label="标签白名单" multiple chips closable-chips variant="outlined" density="compact" hide-details />
            <p class="field-help">命中任一白名单标签即可。</p>
          </div>
          <div class="config-field">
            <label class="field-label" for="rapid-exclude">标签黑名单</label>
            <v-combobox id="rapid-exclude" v-model="config.exclude_tags" aria-label="标签黑名单" multiple chips closable-chips variant="outlined" density="compact" hide-details />
            <p class="field-help">黑名单优先，例如已整理、BDMV。</p>
          </div>
        </div>
        <div class="config-note">未整理 → 已整理 → 已上传<br />MP确认已整理后移除未整理；整个种子全部选中文件上传完成后添加已上传。普通下载列表、按Hash查询及其他类型下载器不受选择限制。使用前请停用独立的qB标签监控插件。</div>
      </section>

      <section v-show="tab === 'bdmv'" aria-label="BDMV上传设置" class="config-panel">
        <div class="switch-row"><div><strong>BDMV 整目录上传</strong><p>定时扫描已完成且同时带有 BDMV、未整理标签的种子</p></div><v-switch v-model="config.bdmv.enabled" aria-label="启用BDMV上传" color="primary" hide-details /></div>
        <div class="field-grid">
          <div class="config-field"><label class="field-label" for="bdmv-time">扫描周期（Cron）</label><v-text-field id="bdmv-time" v-model="config.bdmv.cron" placeholder="0 2 * * *" aria-label="扫描周期（Cron）" variant="outlined" density="compact" hide-details /><p class="field-help">分 时 日 月 周，空格分隔。默认 0 2 * * *（每天02:00）；*/30 * * * * 为每30分钟。使用 MP 时区，周建议填 mon–sun。</p></div>
          <div class="config-field"><label class="field-label" for="bdmv-plugin">CloudDrive2储存插件 ID</label><v-text-field id="bdmv-plugin" v-model="config.bdmv.cd2_plugin_id" aria-label="CloudDrive2储存插件ID" variant="outlined" density="compact" hide-details /><p class="field-help">默认 CloudDriveDisk，复用其连接。</p></div>
        </div>
        <div class="config-field"><label class="field-label" for="bdmv-downloaders">扫描的 qB 下载器</label><v-select id="bdmv-downloaders" v-model="config.bdmv.downloaders" :items="downloaders" aria-label="BDMV下载器" multiple chips closable-chips variant="outlined" density="compact" hide-details /><p class="field-help">必须选择；独立于普通整理的标签黑名单。</p></div>
        <div class="mapping-toolbar"><v-select v-if="config.bdmv.mappings.length" v-model="bdmvMappingIndex" :items="bdmvMappingOptions" aria-label="选择BDMV映射" variant="outlined" density="compact" hide-details class="mapping-select" /><span v-else class="field-help">尚未配置 BDMV 映射</span><v-btn size="small" variant="tonal" color="primary" @click="addBdmvMapping">添加映射</v-btn></div>
        <template v-if="bdmvMapping">
          <div v-for="field in bdmvFields" :key="field.key" class="config-field"><label class="field-label" :for="`bdmv-${field.key}`">{{ field.title }}</label><v-text-field :id="`bdmv-${field.key}`" v-model="bdmvMapping[field.key]" :aria-label="field.title" :placeholder="field.example" variant="outlined" density="compact" hide-details /><p class="field-help">{{ field.help }}</p></div>
          <v-btn color="error" variant="text" size="small" class="align-self-end" @click="removeBdmvMapping">删除此映射</v-btn>
        </template>
        <div class="config-note">CD2 必须已添加本地存储，并能看到下载目录。整目录上传核验完成后添加已上传、移除未整理，保留 BDMV。始终保留本地文件做种。</div>
      </section>
    </fieldset>
    <footer class="config-footer">
      <span class="footer-hint">切换分页保留未保存内容</span>
      <v-btn variant="text" :disabled="saving" @click="emit('close')">关闭</v-btn>
      <v-btn color="primary" variant="flat" :disabled="loading || loadFailed" :loading="saving" @click="save">保存配置</v-btn>
    </footer>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { PLUGIN_ID, normalizeConfig, validateAndSave, libraryOptions, qbOptions } from './shared'

const props = defineProps({
  initialConfig: { type: Object, default: () => ({}) },
  api: { type: [Object, Function], default: () => ({}) },
  pluginId: { type: String, default: PLUGIN_ID },
})
const emit = defineEmits(['save', 'close'])
const config = reactive(normalizeConfig(props.initialConfig))
const afterUpload = computed({
  get: () => config.delete_after_upload ? (config.remove_empty_parents ? 'delete_empty' : 'delete') : 'keep',
  set: value => {
    config.delete_after_upload = value !== 'keep'
    config.remove_empty_parents = value === 'delete_empty'
  },
})
const loading = ref(true)
const loadFailed = ref(false)
const saving = ref(false)
const error = ref('')
const downloaders = ref([])
const downloaderError = ref('')
async function loadDownloaders() {
  downloaderError.value = ''
  try {
    downloaders.value = qbOptions(await props.api.get('download/clients'))
  } catch (failure) {
    downloaders.value = []
    downloaderError.value = failure?.message || '读取下载器失败'
  }
}
const directories = ref([])
const directoryError = ref('')
async function loadDirectories() {
  directoryError.value = ''
  try {
    directories.value = libraryOptions(await props.api.get('storage/directories', {
      params: { directory_type: 'library', storage_type: 'local' },
    }))
  } catch (failure) {
    directories.value = []
    directoryError.value = failure?.message || '读取目录管理失败'
  }
}
const tab = ref('general')
const bdmvMappingIndex = ref(0)
const bdmvMapping = computed(() => config.bdmv.mappings[bdmvMappingIndex.value])
const bdmvMappingOptions = computed(() => config.bdmv.mappings.map((item, index) => ({ title: `${index + 1}. ${item.local_root || '新目录映射'}`, value: index })))
const bdmvFields = [
  { key: 'local_root', title: 'MP可见下载根目录', example: '/downloads', help: '使用 MP 下载器路径映射转换后的目录。' },
  { key: 'cd2_source_root', title: 'CD2本地存储根目录', example: '/本地存储/downloads', help: 'CD2 文件列表中的本地源目录，并非系统挂载点。' },
  { key: 'cd2_target_root', title: 'CD2中的115目标根目录', example: '/115/原盘', help: '保留下载根下的相对目录；目标父目录不存在时自动创建。' },
]
function addBdmvMapping() {
  config.bdmv.mappings.push({ local_root: '', cd2_source_root: '', cd2_target_root: '' })
  bdmvMappingIndex.value = config.bdmv.mappings.length - 1
}
function removeBdmvMapping() {
  config.bdmv.mappings.splice(bdmvMappingIndex.value, 1)
  bdmvMappingIndex.value = Math.max(0, bdmvMappingIndex.value - 1)
}
const mappingIndex = ref(0)
const mapping = computed(() => config.mappings[mappingIndex.value])
const mappingOptions = computed(() => config.mappings.map((item, index) => ({
  title: `${index + 1}. ${item.library_root || '新目录映射'}`,
  value: index,
})))
function addMapping() {
  config.mappings.push({ library_root: '', remote_root: '', max_attempts: 3, initial_delay_minutes: 0, retry_minutes: [60, 360, 1440] })
  mappingIndex.value = config.mappings.length - 1
}
function removeMapping() {
  config.mappings.splice(mappingIndex.value, 1)
  mappingIndex.value = Math.max(0, Math.min(mappingIndex.value, config.mappings.length - 1))
}

async function save() {
  if (loading.value || loadFailed.value || saving.value) return
  if (config.mappings.some(item => !directories.value.some(option => option.value === item.library_root))) {
    tab.value = 'mappings'
    error.value = '请为每组映射选择MP目录管理中的本地整理目标'
    return
  }
  if (config.qb_enabled && (downloaderError.value || config.downloaders.some(
    name => !downloaders.value.some(option => option.value === name)
  ))) {
    tab.value = 'qb'
    error.value = '请重新读取并选择当前已启用的qB下载器'
    return
  }
  if (config.bdmv.enabled && (downloaderError.value || !config.bdmv.downloaders.length || config.bdmv.downloaders.some(name => !downloaders.value.some(option => option.value === name)))) {
    tab.value = 'bdmv'
    error.value = '请选择当前已启用的BDMV下载器'
    return
  }
  saving.value = true
  error.value = ''
  try {
    await validateAndSave(props.api, props.pluginId, config, emit)
  } catch (failure) {
    error.value = failure?.message || String(failure)
  } finally {
    saving.value = false
  }
}

onMounted(async () => {
  try {
    const result = await props.api.get(`plugin/${props.pluginId || PLUGIN_ID}`)
    Object.assign(config, normalizeConfig(result))
    await Promise.all([loadDirectories(), loadDownloaders()])
  } catch (failure) {
    loadFailed.value = true
    error.value = `读取配置失败，请重新打开配置页：${failure?.message || failure}`
  } finally {
    loading.value = false
  }
})
</script>

<style scoped>
.upload-config { display: flex; flex-direction: column; height: min(680px, 82dvh); min-height: 320px; width: 100%; max-width: 860px; margin-inline: auto; overflow: hidden; font-size: 14px; }
.config-header { padding: 20px 24px 12px; flex: none; }
.config-title { font-size: 19px; font-weight: 600; line-height: 1.5; }
.config-subtitle { margin: 4px 0 0; font-size: 13px; opacity: .65; }
.config-tabs { flex: none; border-bottom: 1px solid rgba(var(--v-border-color), var(--v-border-opacity)); }
.config-error { flex: none; margin: 12px 24px 0; }
.config-body { border: 0; margin: 0; padding: 24px; min-width: 0; min-height: 0; flex: 1; overflow-y: auto; overscroll-behavior: contain; }
.config-panel { display: flex; flex-direction: column; gap: 22px; }
.switch-row { display: flex; align-items: center; justify-content: space-between; gap: 20px; }
.switch-row strong { font-weight: 500; }
.switch-row p { margin: 4px 0 0; font-size: 12px; opacity: .65; line-height: 1.6; }
.switch-row :deep(.v-input) { flex: 0 0 auto; }
.field-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 22px; }
.config-field { min-width: 0; }
.field-label { display: block; font-size: 13px; font-weight: 500; line-height: 1.5; margin-bottom: 10px; }
.field-help { display: block; font-size: 12px; line-height: 1.6; opacity: .65; margin: 8px 0 0; overflow-wrap: anywhere; }
.field-unit { font-weight: 400; opacity: .6; margin-left: 6px; }
.config-note { padding: 12px 14px; background: rgba(var(--v-theme-on-surface), .04); border-radius: 8px; font-size: 12px; line-height: 1.8; color: rgba(var(--v-theme-on-surface), .7); }
.mapping-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.mapping-select { min-width: 0; flex: 1; }
.retry-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 14px; }
.retry-field { min-width: 0; }
.retry-field > label { margin: 0 0 8px; }
.retry-input { display: flex; align-items: center; gap: 4px; }
.retry-input :deep(.v-input) { min-width: 0; }
.add-retry { margin-top: 10px; }
.mapping-bottom { display: flex; align-items: center; gap: 12px; justify-content: space-between; }
.mapping-bottom p { margin: 0; }
.mapping-bottom :deep(.v-btn) { flex-shrink: 0; }
.empty-mappings { padding: 40px 16px; text-align: center; font-size: 13px; opacity: .65; line-height: 1.8; }
.config-footer { flex: none; display: flex; align-items: center; gap: 10px; padding: 14px 24px; border-top: 1px solid rgba(var(--v-border-color), var(--v-border-opacity)); }
.footer-hint { flex: 1; font-size: 12px; opacity: .55; }
.upload-config :deep(.v-field__input) { font-size: 14px; }
.upload-config :deep(.v-input__details) { display: none; }
@media (max-width: 600px) {
  .config-header { padding: 16px; }
  .config-body { padding: 20px 16px; }
  .config-footer { padding: 12px 16px; }
  .field-grid { grid-template-columns: minmax(0, 1fr); }
  .retry-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .footer-hint { display: none; }
  .config-footer { justify-content: flex-end; }
  .mapping-bottom { align-items: flex-start; flex-direction: column; }
}
</style>
