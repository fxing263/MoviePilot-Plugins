<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { TransferHistory } from '@/api/types'
import { rapid115TasksForHistory, type Rapid115Snapshot } from '@/composables/useRapid115History'

const props = defineProps<{ history: TransferHistory; snapshot: Rapid115Snapshot; failed: boolean }>()
const { t } = useI18n()
const tasks = computed(() => rapid115TasksForHistory(props.snapshot.tasks, props.history))
/** 未配置上传的目录不显示占位行；删除映射后仍保留已关联任务的历史状态。 */
const showUpload = computed(() => tasks.value.length > 0 || (props.snapshot.mappings || []).some(mapping => {
  const root = mapping.library_root.endsWith('/') ? mapping.library_root.slice(0, -1) : mapping.library_root
  const destination = props.history.dest || ''
  return root && (destination === root || destination.startsWith(`${root}/`))
}))

/** 只展示服务器确认的状态；查询失败时不把旧的“已上传”伪装成最新结果。 */
function stateLabel(state: string) {
  return props.failed ? t('rapid115.unavailable') : t(`rapid115.${state}`)
}
</script>

<template>
  <div v-if="history.status && history.dest_storage === 'local' && showUpload" class="rapid115-history-status">
    <div v-for="task in tasks" :key="task.id" class="rapid115-history-status__row">
      <VChip
        variant="tonal"
        size="small"
        label
        class="my-1"
        :color="!failed && task.state === 'uploaded' ? 'success' : 'primary'"
        >115</VChip
      >
      <small v-if="task.upload_mode === 'normal'">{{ t('rapid115.normal') }}</small>
      <small class="rapid115-history-status__path">{{ task.remote_path }}</small>
      <small
        :class="{
          'text-success': !failed && task.state === 'uploaded',
          'text-error': failed || task.state === 'blocked',
        }"
        >{{ stateLabel(task.state) }}</small
      >
      <small v-if="!snapshot.enabled && ['waiting', 'running'].includes(task.state)">{{ t('rapid115.paused') }}</small>
      <small v-if="!failed && task.state === 'waiting' && task.ready_at" class="text-medium-emphasis">{{
        t('rapid115.nextAttempt', { time: new Date(task.ready_at * 1000).toLocaleString() })
      }}</small>
      <small v-if="!failed && task.error" class="text-medium-emphasis">{{ task.error }}</small>
    </div>
    <div v-if="tasks.length === 0" class="rapid115-history-status__row" :title="t('rapid115.newEventsOnly')">
      <VChip variant="tonal" size="small" label class="my-1">115</VChip>
      <small>{{ failed ? t('rapid115.unavailable') : t('rapid115.notQueued') }}</small>
      <small v-if="!failed && !snapshot.enabled" class="text-medium-emphasis">{{ t('rapid115.paused') }}</small>
    </div>
  </div>
</template>

<style scoped>
.rapid115-history-status__row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.35rem;
}
.rapid115-history-status__path {
  overflow-wrap: anywhere;
}
</style>
