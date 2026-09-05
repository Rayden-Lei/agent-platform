import { create } from 'zustand'
import { getSystemStatus, type SystemStatus } from '../api'
import { errorText } from '../utils/errors'

// 系统状态（降级项、熔断、调度器）的全局 store：多个订阅者共用一个定时器（取最小间隔），
// 页面不可见时暂停、回到可见时立刻刷新一次；只有 admin / developer 能订阅（caller 对 /system/status 是 403）。
interface SystemStatusState {
  status: SystemStatus | null
  error: string | null
  loadedAt: number | null
  refresh: () => Promise<void>
  subscribe: (intervalMs: number) => () => void
}

let timer: ReturnType<typeof setInterval> | null = null
const intervals = new Map<number, number>() // 订阅 id → 间隔
let nextId = 1
let visibilityBound = false

function rearm(refresh: () => Promise<void>) {
  if (timer) clearInterval(timer)
  timer = null
  if (intervals.size === 0) return
  const interval = Math.min(...intervals.values())
  timer = setInterval(() => { if (document.visibilityState === 'visible') refresh() }, interval)
}

export const useSystemStatusStore = create<SystemStatusState>((set, get) => ({
  status: null,
  error: null,
  loadedAt: null,
  refresh: async () => {
    try {
      const status = await getSystemStatus()
      set({ status, error: null, loadedAt: Date.now() })
    } catch (e) {
      set({ error: errorText(e, '获取系统状态失败') })
    }
  },
  subscribe: (intervalMs) => {
    const id = nextId++
    intervals.set(id, intervalMs)
    if (!visibilityBound) {
      visibilityBound = true
      document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible' && intervals.size) get().refresh() })
    }
    // 首个订阅者或距上次加载超过一个间隔时立即刷新一次
    const { loadedAt, refresh } = get()
    if (!loadedAt || Date.now() - loadedAt > intervalMs) refresh()
    rearm(refresh)
    return () => {
      intervals.delete(id)
      rearm(get().refresh)
    }
  },
}))
