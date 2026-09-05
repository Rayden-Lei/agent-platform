import { useState } from 'react'
import { message } from 'antd'
import { resumeWorkflow, type RunRow } from '../../api'
import { errorText } from '../../utils/errors'

// 人工审核：把 approved / rejected 决策提交给后端，恢复被中断的工作流；成功后由调用方刷新列表或详情。
export function useReview(onDone?: () => void) {
  const [reviewing, setReviewing] = useState<number | null>(null)
  const review = async (run: Pick<RunRow, 'id' | 'workflow_id'>, decision: 'approved' | 'rejected') => {
    if (!run.workflow_id) return
    setReviewing(run.id)
    try {
      await resumeWorkflow(run.workflow_id, run.id, { decision })
      message.success(decision === 'approved' ? '已通过，工作流继续执行' : '已拒绝')
      onDone?.()
    } catch (e) {
      message.error(errorText(e, '提交审核结果失败'))
    } finally {
      setReviewing(null)
    }
  }
  return { reviewing, review }
}
