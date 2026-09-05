// 从 axios 错误里取可展示的文案：字符串 detail（400 / 404 / 409 / 5xx 已由拦截器拼好 trace）直接用；
// 422 是 FastAPI 的逐字段数组，取首条 msg 并去掉 "Value error, " 前缀。
export function errorText(e: unknown, fallback = '操作失败'): string {
  const detail = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
  if (Array.isArray(detail)) {
    const first = detail[0] as { msg?: string; loc?: unknown[] } | undefined
    const msg = first?.msg ? first.msg.replace(/^Value error, /, '') : ''
    return msg || fallback
  }
  if (typeof detail === 'string' && detail) return detail
  const message = (e as { message?: string })?.message
  return message && !/Network Error|timeout/i.test(message) ? message : fallback
}
