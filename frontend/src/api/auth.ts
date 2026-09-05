import { get, post } from './core'

export interface CurrentUser {
  id: number
  username: string
  role: 'admin' | 'developer' | 'caller' | string
  is_active: boolean
}

export const login = (data: { username: string; password: string }) => post<{ token: string; user: CurrentUser }>('/auth/login', data)
export const me = () => get<CurrentUser>('/auth/me')
