import { useEffect, useState } from 'react'
import { toast } from "sonner"
import { listModels, type ModelRow } from '../api'
import { errorText } from '../utils/errors'

// 对话页的可对话模型下拉：逻辑比智能体简单——模型没有"发布"这一步，也没有按名称搜的深链需求，
// 所以一次性取一页（100 个）就够；超过一页时打开下拉在本地按名字过滤，不再走服务端搜索。
// 只取启用的：停用的模型在后端会直接拒绝对话，列出来只会让人点了报错。
// enabled 为假时不请求：caller 没有 /models 权限，发出去只会拿到 403 再弹一次错误提示。
export function useAvailableModels(enabled = true) {
  const [items, setItems] = useState<ModelRow[]>([])
  const [loaded, setLoaded] = useState(false)

  useEffect(() => {
    if (!enabled) return
    listModels({ page: 1, page_size: 100, is_enabled: true })
      .then((p) => setItems(p.items))
      .catch((e) => toast.error(errorText(e, '加载模型失败')))
      .finally(() => setLoaded(true))
  }, [enabled])

  return { items, loaded }
}
