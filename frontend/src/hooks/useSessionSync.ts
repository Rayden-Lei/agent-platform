import { useEffect, useRef } from 'react'
import { me } from '../api'
import { useAuth } from '../store/auth'

const MIN_INTERVAL_MS = 60_000 // 切回页面频繁时最多一分钟同步一次

// 登录态同步（docs/15 OP-02）：进入应用、以及页面从后台切回前台时调 /auth/me，刷新角色、菜单与"必须改密"——
// 管理员改了角色或停用账号后，开着的旧页面不用等下一次报错才知道（停用账号的 /auth/me 返回 401，拦截器带回登录页并提示原因）。
// 此前 me() 定义了没人调，角色只在登录时取一次。
export function useSessionSync() {
  const setAuth = useAuth((s) => s.setAuth)
  const last = useRef(0)
  useEffect(() => {
    const sync = () => {
      const token = localStorage.getItem('token')
      if (!token || Date.now() - last.current < MIN_INTERVAL_MS) return
      last.current = Date.now()
      // 401 由 axios 拦截器统一处理（清登录态回登录页）；网络错误不打断使用，下次切回页面再同步
      me().then((user) => setAuth(token, user), () => undefined)
    }
    const onVisible = () => { if (document.visibilityState === 'visible') sync() }
    sync()
    document.addEventListener('visibilitychange', onVisible)
    return () => document.removeEventListener('visibilitychange', onVisible)
  }, [setAuth])
}
