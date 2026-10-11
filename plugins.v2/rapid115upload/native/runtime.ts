import { ApiRequestError } from './src/api/client'
export let client: any
export let instanceId = 'Rapid115Upload'
export function configure(api: any, id: string) { client = api; instanceId = id }
/** 原版宿主API使用解包数据；插件SDK返回envelope，保留失败回执供原版弹窗显示。 */
const api = new Proxy({}, { get(_target, method: string) {
 if (method === 'defaults') return client?.defaults
 if (method === 'getUri') return (...args: any[]) => client.getUri(...args)
 return async (path: string, ...args: any[]) => {
  const scoped = path.replace('plugin/Rapid115Upload/', `plugin/${instanceId}/`)
  const response = await client[method](scoped, ...args)
  if (response?.success === false) throw new ApiRequestError(response.message || '请求失败', { businessFailure: true, payload: response })
  return response?.success === true ? response.data : response
 }
}})
export default api
export * from './src/api/client'
