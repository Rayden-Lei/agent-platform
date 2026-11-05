import { useEffect, useState } from 'react'
import { toast } from "sonner"
import { listWorkflows, type WorkflowRow } from '../api'
import { errorText } from '../utils/errors'

// 对话页的可对话工作流下拉：口径与 useAvailableModels 一致，一次性取一页（100 个），下拉里本地按名字过滤。
// 不按 status 过滤：工作流能不能作为对话目标取决于它的开始节点声明（见对话页），由页面逐个判定并提示原因。
// enabled 为假时不请求：caller 没有 /workflows 权限，避免白拿一个 403。
export function useAvailableWorkflows(enabled = true) {
  const [items, setItems] = useState<WorkflowRow[]>([])
  const [loaded, setLoaded] = useState(false)

  useEffect(() => {
    if (!enabled) return
    listWorkflows({ page: 1, page_size: 100 })
      .then((p) => setItems(p.items))
      .catch((e) => toast.error(errorText(e, '加载工作流失败')))
      .finally(() => setLoaded(true))
  }, [enabled])

  return { items, loaded }
}
