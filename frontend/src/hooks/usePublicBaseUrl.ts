import { me } from '../api'
import { useAsyncData } from './useAsyncData'

// 对外地址（docs/15 PB-07）：服务端 PUBLIC_BASE_URL 经 /auth/me 下发，分享链接与 API 调用示例都用它。
// 没配置、或这次没取到时，用浏览器当前访问的地址——示例照样能用，只是可能是内网地址（08 第 3 节提示上线前配好）。
export function usePublicBaseUrl(): { baseUrl: string; configured: boolean } {
  const { data } = useAsyncData(me, [], { errorText: '加载对外地址失败' })
  const configured = !!data?.public_base_url
  return { baseUrl: data?.public_base_url || window.location.origin, configured }
}
