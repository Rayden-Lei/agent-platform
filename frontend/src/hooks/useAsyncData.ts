import { useCallback, useEffect, useRef, useState } from 'react'
import { errorText } from '../utils/errors'

// 详情页、抽屉、统计卡的异步加载：三态（加载 / 错误 / 数据）+ 请求序号丢过期响应（docs/07 第 3 节"自写异步加载必须二选一"）。
export interface AsyncDataOptions {
  errorText?: string
  auto?: boolean
  /** 依赖变化时是否先清空旧数据（默认 true）。
   *
   *  依赖数组代表「在加载哪个对象」时（/agents/:id、/knowledge-bases/:id 这类详情页）必须为 true：
   *  否则从 A 跳到 B 的加载期间，页面仍显示 A 的名称、统计与操作按钮，
   *  用户可能在几百毫秒内对 A 按下"发布"或"删除"（docs/07 第 3 节）。
   *
   *  依赖只是「刷新条件」时（同一对象换个筛选参数、翻页）保持数据、只置 loading 更平滑，可传 false。
   */
  resetOnDepsChange?: boolean
}

export function useAsyncData<T>(fetcher: () => Promise<T>, deps: unknown[], options: AsyncDataOptions = {}) {
  const { errorText: fallback = '加载失败', auto = true, resetOnDepsChange = true } = options
  const [data, setData] = useState<T | null>(null)
  const [loading, setLoading] = useState(auto)
  const [error, setError] = useState<string | null>(null)
  const seq = useRef(0)
  const fetcherRef = useRef(fetcher)
  fetcherRef.current = fetcher
  // 首次挂载不必清（data 本来就是 null），跳过可以少一次无谓渲染
  const mounted = useRef(false)

  const reload = useCallback(async (silent = false) => {
    const mine = ++seq.current
    if (!silent) setLoading(true)
    try {
      const result = await fetcherRef.current()
      if (mine !== seq.current) return
      setData(result)
      setError(null)
    } catch (e) {
      if (mine !== seq.current) return
      setError(errorText(e, fallback))
    } finally {
      if (mine === seq.current) setLoading(false)
    }
  }, [fallback])

  useEffect(() => {
    if (!auto) return
    if (mounted.current && resetOnDepsChange) {
      // 换了对象：先清掉旧数据与旧错误，和下面的 setLoading(true) 同一批提交，
      // 这样骨架屏立刻出现，不会有一帧旧内容漏出来
      setData(null)
      setError(null)
    }
    mounted.current = true
    reload()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, auto])

  return { data, loading, error, reload, setData }
}
