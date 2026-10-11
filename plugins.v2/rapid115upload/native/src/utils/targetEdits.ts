interface PreviewTarget {
  source?: string
  target?: string
  success?: boolean
  overwrite_skipped?: boolean
}

/** 编辑值独立于原始预览，恢复默认不会丢失 MP 的原始命名结果。 */
export function getTargetOverrides(items: PreviewTarget[], edits: Record<string, string>) {
  const originals = new Map(items.map(item => [item.source, item.target]))
  return Object.entries(edits)
    .filter(([source, target]) => target !== originals.get(source))
    .map(([source, target]) => ({ source, target }))
}

/** 提交前拦截无效路径和批次内目标冲突；库根与文件安全仍由服务端最终校验。 */
export function validateTargetEdits(items: PreviewTarget[], edits: Record<string, string>) {
  const errors: Record<string, string> = {}
  if (!Object.keys(edits).length) return errors
  const seen = new Map<string, string>()
  for (const source of Object.keys(edits)) {
    const matches = items.filter(item => item.source === source && item.success !== false && !item.overwrite_skipped)
    if (matches.length !== 1) errors[source] = '预览来源不唯一或不可整理，请重新预览'
  }
  for (const item of items) {
    if (!item.source || item.success === false || item.overwrite_skipped) continue
    const path = edits[item.source] ?? item.target ?? ''
    if (Object.hasOwn(edits, item.source)) {
      if (!path.startsWith('/') || path.endsWith('/') || path === '/' || path.split('/').some(part => part === '.' || part === '..') || /[\x00-\x1f\\]/.test(path)) {
        errors[item.source] = '请输入包含文件名的绝对路径，不能包含 .、..、反斜杠或控制字符'
      }
    }
    const normalized = path.replace(/\/+/g, '/')
    const other = seen.get(normalized)
    if (other && other !== item.source) {
      errors[item.source] = '与本批次其他文件的目标路径重复'
      errors[other] = '与本批次其他文件的目标路径重复'
    } else seen.set(normalized, item.source)
  }
  return errors
}
