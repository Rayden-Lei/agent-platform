import { useCallback, useState } from 'react'
import { message } from 'antd'
import type { BatchResult } from '../api'
import { errorText } from '../utils/errors'

// 批量操作的状态机：执行中标记、结果（成功 / 失败清单）、结果弹窗开关。
// 后端批量接口逐条返回，失败清单非空时打开结果弹窗让用户看清是哪几条失败（docs/07 第 3 节）。
export function useBatchAction(onFinished?: () => void) {
  const [running, setRunning] = useState(false)
  const [result, setResult] = useState<BatchResult | null>(null)

  const run = useCallback(async (fn: () => Promise<BatchResult>, successText = '已完成') => {
    setRunning(true)
    try {
      const res = await fn()
      if (res.failed.length === 0) message.success(`${successText}（${res.succeeded.length} 项）`)
      else setResult(res)
      onFinished?.()
    } catch (e) {
      message.error(errorText(e, '批量操作失败'))
    } finally {
      setRunning(false)
    }
  }, [onFinished])

  return { running, result, run, closeResult: () => setResult(null) }
}
