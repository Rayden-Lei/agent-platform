import client from './client'

// ===== 接口封装层的公共契约 =====
// 所有接口的唯一下游：页面只从 '../api' import，不直接碰 axios。
// 约定一：响应已被 client 拦截器解包成 res.data，下面直接按业务类型收窄。
// 约定二：列表接口统一返回 Page<T> 分页结构（见下），page/page_size 由 usePagedList 传递。

// ===== 分页契约（docs/04-接口设计.md 2.3）=====
export interface Page<T = any> {
  items: T[]
  total: number
  page: number
  page_size: number
}
// 分页查询参数：page/page_size 可选，其余字段（如 status、sort、order、started_from）透传给后端做筛选与排序
export type PageQuery = { page?: number; page_size?: number } & Record<string, string | number | boolean | undefined>

// 拦截器已把响应解包成 res.data，这里只是把类型收窄，避免每个页面各写一遍 as any
export const get = <T = any>(url: string, params?: object) => client.get(url, { params }) as unknown as Promise<T>
export const post = <T = any>(url: string, data?: unknown) => client.post(url, data) as unknown as Promise<T>
export const put = <T = any>(url: string, data?: unknown) => client.put(url, data) as unknown as Promise<T>
export const del = <T = any>(url: string) => client.delete(url) as unknown as Promise<T>

// 下拉选项用：取第一页最多 100 条。超过 100 条时应改为带 q 的服务端搜索，见 docs/09
export const OPTIONS_PAGE: PageQuery = { page: 1, page_size: 100 }

// ===== 批量操作契约（docs/04 2.3）：逐条独立执行，永远 200，失败进清单 =====
export interface BatchResult {
  succeeded: number[]
  failed: { id: number; detail: string }[]
}
export const batchAction = (resourcePath: string, ids: number[], action: string) =>
  post<BatchResult>(`${resourcePath}/batch`, { ids, action })

export interface OkResponse { code: number; message: string }
