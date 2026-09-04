// 登录态全局 store（zustand）：token 与用户信息持久化在 localStorage，
// 刷新页面后从 localStorage 恢复，供路由守卫、布局和请求层读取
import { create } from 'zustand'

interface AuthState {
  token: string | null // JWT 令牌，null 表示未登录
  user: any | null // 当前登录用户信息（用户名、角色等），结构以后端返回为准
  setAuth: (token: string, user: any) => void // 登录成功后写入内存态并持久化
  logout: () => void // 退出登录：清空内存态与 localStorage
}

// 从 localStorage 恢复存储的用户信息；存储被篡改/损坏导致 JSON 非法时回退为未登录，
// 避免在模块顶层同步 JSON.parse 抛异常拖垮整个应用 import
function restoreUser(): any {
  const raw = localStorage.getItem('user')
  if (!raw) return null
  try {
    return JSON.parse(raw)
  } catch {
    localStorage.removeItem('user') // 清掉坏数据，避免每次刷新都再触发
    return null
  }
}

export const useAuth = create<AuthState>((set) => ({
  // 初始化时从 localStorage 恢复登录态（页面刷新后仍保持登录）
  token: localStorage.getItem('token') || null,
  user: restoreUser(),
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
