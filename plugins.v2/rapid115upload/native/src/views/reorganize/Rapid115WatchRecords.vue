<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import type { Rapid115Snapshot } from '@/composables/useRapid115History'

const props = defineProps<{ snapshot: Rapid115Snapshot; failed: boolean }>()
const { t } = useI18n()
const search = ref('')
const tasks = computed(() => props.snapshot.tasks.filter(task => task.origin === 'watch'))
const headers = [
  { title: '文件 / 路径', key: 'source_path' },
  { title: '状态', key: 'state', width: 220 },
]
</script>

<template>
  <VCard v-if="tasks.length" class="mb-4">
    <VCardTitle class="d-flex align-center flex-wrap ga-2">
      目录监控 · 115秒传
      <VChip size="small" variant="tonal">{{ tasks.length }}</VChip>
    </VCardTitle>
    <VCardText>
      <VTextField
        v-model="search"
        label="搜索监控记录"
        prepend-inner-icon="mdi-magnify"
        hide-details
        density="compact"
        clearable
      />
    </VCardText>
    <VDataTable
      :headers="headers"
      :items="tasks"
      :search="search || ''"
      :items-per-page="10"
      item-value="id"
      density="compact"
    >
      <template #item.source_path="{ item }">
        <div class="py-3 watch-paths">
          <strong>{{ item.source_path.split('/').pop() }}</strong>
          <div>源路径：{{ item.source_path }}</div>
          <div>115路径：{{ item.remote_path }}</div>
        </div>
      </template>
      <template #item.state="{ item }">
        <VChip size="small" variant="tonal" :color="!failed && item.state === 'uploaded' ? 'success' : 'primary'">
          {{ failed ? t('rapid115.unavailable') : t(`rapid115.${item.state}`) }}
        </VChip>
        <div v-if="!snapshot.enabled" class="text-caption">{{ t('rapid115.paused') }}</div>
        <div v-if="!failed && item.error" class="text-caption">{{ item.error }}</div>
        <div v-if="!failed && item.ready_at" class="text-caption">
          {{ t('rapid115.nextAttempt', { time: new Date(item.ready_at * 1000).toLocaleString() }) }}
        </div>
      </template>
    </VDataTable>
  </VCard>
</template>

<style scoped>
.watch-paths {
  overflow-wrap: anywhere;
  min-width: 180px;
  line-height: 1.8;
}
</style>
