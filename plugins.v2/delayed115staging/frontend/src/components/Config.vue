<template>
  <div class="pa-4">
    <div class="text-h6 mb-3">115 延迟暂存配置</div>
    <v-alert v-if="error" type="error" variant="tonal" class="mb-3">{{ error }}</v-alert>
    <v-progress-linear v-if="loading" indeterminate class="mb-3" />
    <fieldset :disabled="loading || saving" class="config-fields">
      <v-switch v-model="config.enabled" label="启用插件" color="primary" hide-details />
      <v-alert type="info" variant="tonal" class="my-4">
        每个整理目录分别设置暂存目录与延迟规则，例如 /pt1 → /115-staging1，/pt2 → /115-staging2。
        各整理目录之间、各暂存目录之间均不能相同或互为父子目录；整理目录与任一暂存目录也不能重叠。
        新配置只用于新任务，已登记任务保留当时的延迟、路径、确认方式与清理选项。
      </v-alert>
      <v-card v-for="(mapping, mappingIndex) in config.mappings" :key="mappingIndex" variant="outlined" class="mb-4 pa-3">
        <div class="d-flex align-center mb-3">
          <strong>目录映射 {{ mappingIndex + 1 }}</strong><v-spacer />
          <v-btn variant="text" color="error" size="small" @click="config.mappings.splice(mappingIndex, 1)">删除映射</v-btn>
        </div>
        <v-text-field v-model="mapping.library_root" label="整理媒体库根目录" :placeholder="`/pt${mappingIndex + 1}`" hint="从此根目录计算相对路径，保留分类、剧名、季等完整目录结构。" persistent-hint class="mb-3" />
        <v-text-field v-model="mapping.staging_root" label="对应的 115 监控暂存目录" :placeholder="`/115-staging${mappingIndex + 1}`" hint="必须与对应源文件处于同一文件系统；不支持硬链接时任务失败，不复制数据。" persistent-hint class="mb-3" />
        <v-alert type="info" variant="tonal" class="mb-3">
          规则目录相对于本组整理根目录，例如 /国产电视剧。填写 / 表示整个根目录，此时不能再添加子目录规则。
          同组规则不能相同或互为父子目录；未匹配文件不处理。大小使用十进制 GB（1 GB = 1,000,000,000 字节），上限不含、下限包含。
        </v-alert>
      <v-card v-for="(rule, index) in mapping.rules" :key="index" variant="outlined" class="mb-3 pa-3">
        <div class="d-flex align-center mb-2">
          <strong>{{ Array.isArray(rule.tiers) ? '按大小延迟' : '固定延迟' }} · 规则 {{ index + 1 }}</strong>
          <v-spacer />
          <v-btn variant="text" color="error" size="small" @click="mapping.rules.splice(index, 1)">删除规则</v-btn>
        </div>
        <v-text-field v-model="rule.directory" label="规则目录（相对于媒体库）" placeholder="/国产电视剧" />
        <v-text-field v-if="!Array.isArray(rule.tiers)" v-model.number="rule.delay_minutes" type="number" min="0" label="延迟（分钟）" />
        <template v-else>
          <v-row v-for="(tier, tierIndex) in rule.tiers" :key="tierIndex" dense>
            <v-col cols="12" sm="6">
              <v-text-field v-if="tierIndex < rule.tiers.length - 1" v-model.number="tier.below_gb" type="number" min="0" label="本档上限 GB（不含）" :prefix="tierIndex ? `≥ ${rule.tiers[tierIndex - 1].below_gb}，<` : '<'" />
              <div v-else class="pt-4">{{ tierIndex ? `≥ ${rule.tiers[tierIndex - 1].below_gb} GB` : '所有大小' }}</div>
            </v-col>
            <v-col cols="9" sm="4"><v-text-field v-model.number="tier.delay_minutes" type="number" min="0" label="延迟（分钟）" /></v-col>
            <v-col cols="3" sm="2"><v-btn v-if="tierIndex < rule.tiers.length - 1" variant="text" color="error" @click="rule.tiers.splice(tierIndex, 1)">删除</v-btn></v-col>
          </v-row>
          <v-btn variant="tonal" size="small" @click="addTier(rule)">新增大小分档</v-btn>
        </template>
      </v-card>
      <div class="d-flex flex-wrap ga-2 mb-4">
        <v-btn variant="tonal" @click="mapping.rules.push({ directory: '', delay_minutes: 60 })">新增固定延迟规则</v-btn>
        <v-btn variant="tonal" @click="mapping.rules.push({ directory: '', tiers: [{ below_gb: 5, delay_minutes: 10 }, { below_gb: 20, delay_minutes: 30 }, { below_gb: null, delay_minutes: 60 }] })">新增大小延迟规则</v-btn>
      </div>
      </v-card>
      <v-btn variant="tonal" class="mb-4" @click="config.mappings.push({ library_root: '', staging_root: '', rules: [{ directory: '/', delay_minutes: 60 }] })">新增整理目录映射</v-btn>
      <v-select v-model="config.confirmation_mode" label="上传成功确认方式" :items="confirmationModes" hint="自动确认仅适用于以此模式新建的任务；切回手动会暂停已有任务的自动确认。" persistent-hint class="mb-3" />
      <v-alert v-if="config.confirmation_mode === 'staging_deleted'" type="warning" variant="tonal" class="mb-3">
        仅适用于上传器在上传成功后删除暂存文件的配置。插件监控暂存目录中的硬链接，不监控 qBittorrent 做种文件。
        暂存文件删除后，经至少间隔 30 秒的两次检查才自动确认并按下方选项清理。无法区分人工删除与上传器删除。
        暂存根目录不可用或被替换时暂停自动确认；根目录正常时，文件或下级目录被删除均可自动确认。
      </v-alert>
      <v-alert v-else type="info" variant="tonal" class="mb-3">在任务页核验远端文件后手动确认，或由上传器提交明确的成功回执，再执行清理。</v-alert>
      <v-switch v-model="config.scan_once" label="进行一次全量硬链接" color="warning" hide-details />
      <v-alert type="info" variant="tonal" class="my-3">启用插件后执行一次：扫描整理目录内匹配规则的普通文件（含字幕、刮削文件），新任务不等待延迟。已有任务不重复创建，扫描成功后自动关闭此选项。中断后重新扫描并去重。</v-alert>
      <v-text-field v-model.number="config.history_days" type="number" min="1" max="3650" label="已完成任务记录保留天数" hint="默认 7 天，每天清理一次。仅删除记录，失败和未完成任务保留；记录过期后再次手动全量扫描可能重新投递仍保留的整理文件。" persistent-hint class="my-3" />
      <v-switch v-model="config.cleanup_organized" label="确认上传成功后，删除对应的整理硬链接" color="warning" hide-details />
      <v-switch v-model="config.cleanup_empty_dirs" label="清理空目录（保留媒体库及暂存根目录）" color="primary" hide-details />
      <v-alert type="info" variant="tonal" class="my-3">插件不上传、不刷新媒体库。下载器源文件与做种清理由现有流程负责。</v-alert>
    </fieldset>
    <div class="d-flex flex-wrap ga-2 mt-4">
      <v-btn variant="text" @click="emit('switch')">任务列表</v-btn>
      <v-spacer />
      <v-btn variant="text" @click="emit('close')">关闭</v-btn>
      <v-btn color="primary" :disabled="loading || loadFailed" :loading="saving" @click="save">验证并保存</v-btn>
    </div>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { PLUGIN_ID, normalizeConfig, validateAndSave } from './shared'

const props = defineProps({
  initialConfig: { type: Object, default: () => ({}) },
  api: { type: [Object, Function], default: () => ({}) },
  pluginId: { type: String, default: PLUGIN_ID },
})
const emit = defineEmits(['save', 'close', 'switch'])
const confirmationModes = [
  { title: '手动确认 / 上传器成功回执', value: 'manual' },
  { title: '上传器删除暂存文件后自动确认', value: 'staging_deleted' },
]
const config = reactive(normalizeConfig(props.initialConfig))
const loading = ref(true)
const loadFailed = ref(false)
const saving = ref(false)
const error = ref('')

function addTier(rule) {
  const previous = rule.tiers[rule.tiers.length - 2]?.below_gb || 0
  rule.tiers.splice(rule.tiers.length - 1, 0, { below_gb: Number(previous) + 5, delay_minutes: 30 })
}

async function save() {
  if (loading.value || loadFailed.value || saving.value) return
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
  } catch (failure) {
    loadFailed.value = true
    error.value = `读取配置失败，请重新打开配置页：${failure?.message || failure}`
  } finally {
    loading.value = false
  }
})
</script>

<style scoped>
.config-fields { border: 0; padding: 0; min-width: 0; }
</style>
