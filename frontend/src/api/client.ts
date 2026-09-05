import axios from 'axios'

// ===== 请求层约定 =====
// 全局唯一的 axios 实例：baseURL 指向后端 /api/v1，30 秒超时。
// 所有 api/index.ts 的接口都走这个实例，不要在别处另建 axios。
const client = axios.create({
  baseURL: '/api/v1',
  timeout: 30000,
})

// 请求拦截器：从 localStorage 取登录 token，注入 Authorization 头（Bearer 前缀）
client.interceptors.request.use((config) => {
  const token = localStorage.getItem('token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

client.interceptors.response.use(
  // 成功时直接解包成响应体（res.data），调用方拿到的就是业务数据而不是 axios 的 Response 包装
  (res) => res.data,
  (err) => {
    // 服务端故障：把追踪 ID 拼进提示，用户报障时截图即可定位到那次请求的全部日志
    const traceId = err.response?.data?.trace_id || err.response?.headers?.['x-request-id']
    if (err.response?.status >= 500 && traceId && err.response?.data?.detail) {
      err.response.data.detail = `${err.response.data.detail}（trace: ${traceId}）`
    }
    // 429：服务端 detail 已写明等待秒数（入口限流）或时长（登录锁定）；只有缺少提示时才用 Retry-After 头补上
    const retryAfter = err.response?.headers?.['retry-after']
    if (err.response?.status === 429 && retryAfter && err.response?.data?.detail && !/重试|再试/.test(err.response.data.detail)) {
      err.response.data.detail = `${err.response.data.detail}（${retryAfter} 秒后可重试）`
    }
    // 401：凭证失效，清掉本地登录态并跳回登录页（统一处理，各页面无需重复写）
    if (err.response?.status === 401) {
      localStorage.removeItem('token')
      localStorage.removeItem('user')
      if (!window.location.pathname.startsWith('/login')) {
        window.location.href = '/login'
      }
    }
    return Promise.reject(err)
  },
)

export default client
