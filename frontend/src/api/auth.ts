import type { ApiKeyRow } from './admin'
import { get, post, put, type Page, type PageQuery } from './core'

export interface CurrentUser {
  id: number
  username: string
  role: 'admin' | 'developer' | 'caller' | string
  is_active: boolean
  must_change_password: boolean // 为真时除改密与 /auth/me 外接口全部 403，页面弹出改密框（docs/15 OP-04）
}

// /auth/me 另带对外地址（docs/15 PB-07）：分享链接、API 调用示例用；空串表示用浏览器当前访问的地址。
// 个人资料（docs/15 OP-03）：手机号只有脱敏值，完整号码任何接口都不返回
export interface MeInfo extends CurrentUser {
  public_base_url: string
  display_name: string | null
  email: string | null
  phone_masked: string | null
  password_changed_at: string | null
  last_login_at: string | null
}
// 不带的字段不改，null 清除
export interface ProfileInput { display_name?: string | null; email?: string | null; phone?: string | null }
export interface LoginRecord { created_at: string; ip: string | null; success: boolean }
type TokenResult = { token: string; user: CurrentUser }

export const login = (data: { username: string; password: string }) => post<TokenResult>('/auth/login', data)
export const me = () => get<MeInfo>('/auth/me')
export const updateMe = (data: ProfileInput) => put<MeInfo>('/auth/me', data)
// 改密与退出其他设备成功后旧令牌全部失效（token_version +1），用返回的新令牌替换当前登录态
export const changeMyPassword = (data: { old_password: string; new_password: string }) => put<TokenResult>('/auth/me/password', data)
export const logoutOtherDevices = () => post<TokenResult>('/auth/me/logout-others')
export const listMyLogins = () => get<LoginRecord[]>('/auth/me/logins')
// 归属本人的 API Key（只读；调用者看的是管理员代发给自己的，docs/15 D-15）
export const listMyApiKeys = (params?: PageQuery) => get<Page<ApiKeyRow>>('/auth/me/api-keys', params)
