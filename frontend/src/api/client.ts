import axios from 'axios'

const client = axios.create({
  baseURL: '/api/v1',
  timeout: 30000,
})

client.interceptors.request.use((config) => {
  const token = localStorage.getItem('token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

client.interceptors.response.use(
  (res) => res.data,
  (err) => {
    // 服务端故障：把追踪 ID 拼进提示，用户报障时截图即可定位到那次请求的全部日志
    const traceId = err.response?.data?.trace_id || err.response?.headers?.['x-request-id']
    if (err.response?.status >= 500 && traceId && err.response?.data?.detail) {
      err.response.data.detail = `${err.response.data.detail}（trace: ${traceId}）`
    }
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
