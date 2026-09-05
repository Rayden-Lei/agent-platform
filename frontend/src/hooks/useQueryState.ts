import { useCallback, useMemo } from 'react'
import { useSearchParams } from 'react-router-dom'

// 把筛选条件放进 URL 查询串：刷新不丢、能分享、详情页的关联跳转（/runs?agent_id=3&status=failed）能落到带筛选的列表。
// 值统一是字符串；缺省值不写进 URL。
export function useQueryState<T extends Record<string, string | undefined>>(defaults: T): [T, (patch: Partial<T>) => void, () => void] {
  const [params, setParams] = useSearchParams()
  const values = useMemo(() => {
    const out = { ...defaults }
    for (const key of Object.keys(defaults)) {
      const v = params.get(key)
      if (v !== null && v !== '') (out as Record<string, string | undefined>)[key] = v
    }
    return out
  }, [params, defaults])

  const setValues = useCallback((patch: Partial<T>) => {
    const next = new URLSearchParams(params)
    for (const [key, value] of Object.entries(patch)) {
      if (value === undefined || value === '' || value === defaults[key]) next.delete(key)
      else next.set(key, String(value))
    }
    setParams(next, { replace: true })
  }, [params, setParams, defaults])

  const reset = useCallback(() => {
    const next = new URLSearchParams(params)
    for (const key of Object.keys(defaults)) next.delete(key)
    setParams(next, { replace: true })
  }, [params, setParams, defaults])

  return [values, setValues, reset]
}
