// 登录态全局 store（zustand）：token 与用户信息持久化在 localStorage，
// 刷新页面后从 localStorage 恢复，供路由守卫、布局和请求层读取
import { create } from 'zustand'

interface AuthState {
  token: string | null // JWT 令牌，null 表示未登录
  user: any | null // 当前登录用户信息（用户名、角色等），结构以后端返回为准
  setAuth: (token: string, user: any) => void // 登录成功后写入内存态并持久化
  logout: () => void // 退出登录：清空内存态与 localStorage
}

export const useAuth = create<AuthState>((set) => ({
  // 初始化时从 localStorage 恢复登录态（页面刷新后仍保持登录）
  token: localStorage.getItem('token'),
  user: JSON.parse(localStorage.getItem('user') || 'null'),
  setAuth: (token, user) => {
    localStorage.setItem('token', token)
    localStorage.setItem('user', JSON.stringify(user))
    set({ token, user })
  },
  logout: () => {
    localStorage.removeItem('token')
    localStorage.removeItem('user')
    set({ token: null, user: null })
  },
}))
