import { computed, onActivated, onDeactivated, onMounted, onUnmounted, ref, watch, type Ref } from 'vue'
import api from '@/api'
import type { TransferHistory } from '@/api/types'

export interface Rapid115Task {
  upload_mode?: string
  links?: { history_id: number | null }[]
  id: string
  origin?: 'transfer' | 'watch'
  created_at?: number
  history_id?: number | null
  source_path: string
  organized_path: string
  remote_path: string
  state: 'waiting' | 'running' | 'uploaded' | 'blocked' | 'cancelled'
  ready_at?: number | null
  error?: string
}

export interface Rapid115Snapshot {
  mappings?: { library_root: string; remote_root: string }[]
  tasks: Rapid115Task[]
  enabled: boolean
  error?: string
}

/** 优先关联整理记录 ID；仅旧的无 ID 任务允许以完整源/目标路径关联。 */
export function rapid115TasksForHistory(tasks: Rapid115Task[], history: TransferHistory): Rapid115Task[] {
  if (!history.status || history.dest_storage !== 'local') return []
  return tasks.filter(task =>
    task.links?.some(link => link.history_id === history.id) || (task.history_id != null
      ? task.history_id === history.id
      : task.organized_path === history.dest && (!task.source_path || task.source_path === history.src)),
  )
}

/** 整张整理列表共用一次插件查询，离开 KeepAlive 页面立即停止轮询及在途回写。 */
export function useRapid115History(allowed: Ref<boolean>) {
  const snapshot = ref<Rapid115Snapshot | null>(null)
  const failed = ref(false)
  let active = false
  let timer: ReturnType<typeof setInterval> | undefined
  let request: AbortController | undefined

  async function refresh() {
    if (!active || !allowed.value || request || document.hidden) return
    const controller = new AbortController()
    request = controller
    try {
      const result = await api.get<Rapid115Snapshot>('plugin/Rapid115Upload/tasks', {
        signal: controller.signal,
        feedback: 'silent',
        skipConnectionTracking: true,
      })
      if (controller.signal.aborted || !active || !allowed.value) return
      if (!Array.isArray(result.tasks) || typeof result.enabled !== 'boolean') {
        throw new Error('Invalid rapid upload response')
      }
      snapshot.value = result
      failed.value = Boolean(result.error)
    } catch (error) {
      if (controller.signal.aborted || !active) return
      const status = (error as { response?: { status?: number } })?.response?.status
      if (status === 404 || status === 403) {
        snapshot.value = null
        failed.value = false
      } else {
        failed.value = true
      }
    } finally {
      if (request === controller) request = undefined
    }
  }

  function start() {
    if (active) return
    active = true
    void refresh()
    timer = setInterval(() => void refresh(), 15_000)
  }

  function stop() {
    active = false
    clearInterval(timer)
    timer = undefined
    request?.abort()
    request = undefined
  }

  watch(allowed, value => {
    if (value) void refresh()
    else {
      request?.abort()
      request = undefined
      snapshot.value = null
    }
  })
  onMounted(start)
  onActivated(start)
  onDeactivated(stop)
  onUnmounted(stop)

  return { snapshot, failed, visible: computed(() => allowed.value && snapshot.value !== null), refresh, stop, start }
}
