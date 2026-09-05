import { useEffect } from 'react'
import { useAuth } from '../store/auth'
import { useSystemStatusStore } from '../store/systemStatus'

// 订阅系统状态：默认 60 秒轮询（模型页熔断倒计时短，可传 30000）；caller 角色不订阅。
export function useSystemStatus(intervalMs = 60000) {
  const role = useAuth((s) => s.user?.role)
  const status = useSystemStatusStore((s) => s.status)
  const error = useSystemStatusStore((s) => s.error)
  const refresh = useSystemStatusStore((s) => s.refresh)
  const subscribe = useSystemStatusStore((s) => s.subscribe)
  const allowed = role === 'admin' || role === 'developer'
  useEffect(() => {
    if (!allowed) return
    return subscribe(intervalMs)
  }, [allowed, intervalMs, subscribe])
  return { status: allowed ? status : null, error, refresh }
}
