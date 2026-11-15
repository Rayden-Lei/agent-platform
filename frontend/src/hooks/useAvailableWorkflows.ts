import { useEffect, useState } from 'react'
import { toast } from "sonner"
import { listWorkflows, OPTIONS_PAGE, type WorkflowRow } from '../api'
import { errorText } from '../utils/errors'

// 对话页的"可对话工作流"下拉：口径与 useAvailableModels 一致，一次性取一页（100 个），下拉里本地按名字过滤。
// **只列已发布的**（FR-075）：工作流对话读线上版本，未发布的工作流选进去也只会 403，
// 列出来等于给用户一个点了就报错的选项。已发布但改了草稿的仍可对话（跑的是线上版本），照常列出。
// enabled 为假时不请求：caller 没有 /workflows 权限，避免白拿一个 403。
export function useAvailableWorkflows(enabled = true) {
  const [items, setItems] = useState<WorkflowRow[]>([])
  const [loaded, setLoaded] = useState(false)

  useEffect(() => {
    if (!enabled) return
    listWorkflows({ ...OPTIONS_PAGE, status: 'published' })
      .then((p) => setItems(p.items))
      .catch((e) => toast.error(errorText(e, '加载工作流失败')))
      .finally(() => setLoaded(true))
  }, [enabled])

  return { items, loaded }
}
