import { useEffect } from 'react'
import { useSearchParams } from 'react-router-dom'

// 抽屉型资源的列表页响应 ResourceLink（/models?open=3）：读一次 ?open= 后触发打开并清掉参数，避免刷新时反复打开。
export function useOpenParam(onOpen: (id: number) => void): void {
  const [params, setParams] = useSearchParams()
  const raw = params.get('open')
  useEffect(() => {
    if (!raw) return
    const id = Number(raw)
    const next = new URLSearchParams(params)
    next.delete('open')
    setParams(next, { replace: true })
    if (Number.isFinite(id) && id > 0) onOpen(id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [raw])
}
