export const PLUGIN_ID = 'Rapid115Upload'

/** 深拷贝宿主配置，保持分身实例与编辑状态互相独立。 */
export function normalizeConfig(response = {}) {
  if (response?.success === false) throw new Error(response.message || '读取配置失败')
  const source = response?.success === true ? response.data : response
  const config = JSON.parse(JSON.stringify(source || {}))
  const normalizeMappings = rows => Array.isArray(rows)
    ? rows.map(mapping => ({ ...mapping, initial_delay_minutes: mapping.initial_delay_minutes ?? 0, max_attempts: mapping.max_attempts ?? config.max_attempts ?? 3 })) : []
  const bdmv = { enabled: false, downloaders: [], cd2_plugin_id: 'CloudDriveDisk', mappings: [], ...(config.bdmv || {}) }
  if (bdmv.cron == null) {
    const legacy = /^(\d{2}):(\d{2})$/.exec(bdmv.time || '02:00')
    bdmv.cron = legacy ? `${Number(legacy[2])} ${Number(legacy[1])} * * *` : ''
  }
  delete bdmv.time
  return { bdmv, remove_empty_parents: config.remove_empty_parents ?? false, delete_after_upload: config.delete_after_upload ?? false, concurrency: config.concurrency ?? 2, qb_enabled: config.qb_enabled ?? false, downloaders: config.downloaders ?? [], include_tags: config.include_tags ?? ['未整理'], exclude_tags: config.exclude_tags ?? ['已整理', 'BDMV'], watch_mappings: normalizeMappings(config.watch_mappings), enabled: config.enabled ?? false, mappings: normalizeMappings(config.mappings) }
}

/** 后端明确验证通过后才交给宿主持久化。 */
export async function validateAndSave(api, pluginId, config, emit) {
  const payload = JSON.parse(JSON.stringify(config))
  const result = await api.post(`plugin/${pluginId || PLUGIN_ID}/validate`, payload)
  if (result?.success !== true) throw new Error(result?.message || '配置验证失败')
  emit('save', payload)
}

export const STATE_LABELS = { waiting: '等待尝试', running: '正在上传', uploaded: '已上传', blocked: '需要处理', cancelled: '已取消' }

/** 后端时间使用 Unix 秒。 */
export function formatTime(value) {
  if (!value) return '—'
  return new Date(value * 1000).toLocaleString()
}

/** 复用系统目录查询，只展示本地整理目标，同路径的分类规则合并为一个选项。 */
export function libraryOptions(response) {
  if (response?.success === false) throw new Error(response.message || '读取目录管理失败')
  const rows = Array.isArray(response) ? response : response?.data
  if (!Array.isArray(rows)) throw new Error('目录管理返回格式无效')
  const options = new Map()
  for (const row of rows) {
    if (row.library_storage !== 'local' || !row.library_path) continue
    const path = row.library_path.replace(/\/+$/, '') || '/'
    if (!options.has(path)) options.set(path, { title: `${row.name || '本地媒体库'} · ${path}`, value: path })
  }
  return [...options.values()]
}

/** 复用宿主可用下载器清单，只保留 qB；不读取连接凭据或发起下载器请求。 */
export function qbOptions(response) {
  if (response?.success === false) throw new Error(response.message || '读取下载器失败')
  const rows = Array.isArray(response) ? response : response?.data
  if (!Array.isArray(rows)) throw new Error('下载器清单返回格式无效')
  return [...new Set(rows.filter(row => row.type === 'qbittorrent' && row.name).map(row => row.name))]
    .map(name => ({ title: name, value: name }))
}
