import { get, post, put } from './core'

export interface CurrentUser {
  id: number
  username: string
  role: 'admin' | 'developer' | 'caller' | string
  is_active: boolean
  must_change_password: boolean // 为真时除改密与 /auth/me 外接口全部 403，页面弹出改密框（docs/15 OP-04）
}

export const login = (data: { username: string; password: string }) => post<{ token: string; user: CurrentUser }>('/auth/login', data)
export const me = () => get<CurrentUser>('/auth/me')
// 改密成功后旧令牌全部失效（token_version +1），用返回的新令牌替换当前登录态
export const changeMyPassword = (data: { old_password: string; new_password: string }) => put<{ token: string; user: CurrentUser }>('/auth/me/password', data)
