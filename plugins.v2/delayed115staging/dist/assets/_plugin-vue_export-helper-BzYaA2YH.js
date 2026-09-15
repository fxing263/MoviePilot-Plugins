const PLUGIN_ID = 'Delayed115Staging';

/** 兼容旧单目录配置和宿主响应封装；深拷贝避免编辑污染宿主缓存。 */
function normalizeConfig(response = {}) {
  if (response?.success === false) throw new Error(response.message || '读取配置失败')
  const source = response?.success === true ? response.data : response;
  const config = JSON.parse(JSON.stringify(source || {}));
  const mappings = Array.isArray(config.mappings) ? config.mappings :
    (config.library_root || config.staging_root || Array.isArray(config.rules)) ?
      [{ library_root: config.library_root || '', staging_root: config.staging_root || '', rules: config.rules || [] }] : [];
  return {
    enabled: config.enabled ?? false,
    scan_once: config.scan_once ?? false,
    history_days: config.history_days ?? 7,
    confirmation_mode: config.confirmation_mode ?? 'manual',
    cleanup_organized: config.cleanup_organized ?? true,
    cleanup_empty_dirs: config.cleanup_empty_dirs ?? true,
    mappings: mappings.map(mapping => ({
      library_root: mapping.library_root || '', staging_root: mapping.staging_root || '',
      rules: Array.isArray(mapping.rules) ? mapping.rules : [],
    })),
  }
}

/** 保存事件交给宿主持久化；后端验证失败时绝不发出该事件。 */
async function validateAndSave(api, pluginId, config, emit) {
  const payload = JSON.parse(JSON.stringify(config));
  const result = await api.post(`plugin/${pluginId || PLUGIN_ID}/validate`, payload);
  if (result?.success !== true) throw new Error(result?.message || '配置验证失败')
  emit('save', payload);
}

const STATE_LABELS = {
  waiting: '等待延迟', staged: '已暂存，待确认上传', linking: '正在暂存',
  failed: '失败', cleanup_failed: '清理失败', confirmed: '已确认上传，等待清理',
  done: '已完成', cancelled: '已取消', uploaded: '已确认上传',
};

/** ready_at 使用后端 Unix 秒数，显示时转换为浏览器本地时间。 */
function formatTime(value) {
  if (!value) return '—'
  const date = new Date(typeof value === 'number' ? value * 1000 : value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString()
}

const _export_sfc = (sfc, props) => {
  const target = sfc.__vccOpts || sfc;
  for (const [key, val] of props) {
    target[key] = val;
  }
  return target;
};

export { PLUGIN_ID as P, STATE_LABELS as S, _export_sfc as _, formatTime as f, normalizeConfig as n, validateAndSave as v };
