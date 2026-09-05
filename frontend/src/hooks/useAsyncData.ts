import { useCallback, useEffect, useRef, useState } from 'react'
import { errorText } from '../utils/errors'

// 详情页、抽屉、统计卡的异步加载：三态（加载 / 错误 / 数据）+ 请求序号丢过期响应（docs/07 第 3 节"自写异步加载必须二选一"）。
export interface AsyncDataOptions { errorText?: string; auto?: boolean }

export function useAsyncData<T>(fetcher: () => Promise<T>, deps: unknown[], options: AsyncDataOptions = {}) {
  const { errorText: fallback = '加载失败', auto = true } = options
  const [data, setData] = useState<T | null>(null)
  const [loading, setLoading] = useState(auto)
  const [error, setError] = useState<string | null>(null)
  const seq = useRef(0)
  const fetcherRef = useRef(fetcher)
  fetcherRef.current = fetcher

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
    if (auto) reload()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, auto])

  return { data, loading, error, reload, setData }
}
