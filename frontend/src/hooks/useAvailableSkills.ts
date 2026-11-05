import { useEffect, useState } from 'react'
import { toast } from "sonner"
import { listSkills, type SkillRow } from '../api'
import { errorText } from '../utils/errors'

// 装配页的技能多选：口径与 useAvailableModels 一致，一次性取一页（100 个），下拉里本地按名字过滤。
// 只取启用的：停用的技能在运行时不会被装配（后端 enabled_skills 直接过滤掉），列出来只会让人绑上一个不生效的技能。
// 技能只占 admin / developer 的权限，enabled 为假时不请求，避免白拿一个 403。
export function useAvailableSkills(enabled = true) {
  const [items, setItems] = useState<SkillRow[]>([])
  const [loaded, setLoaded] = useState(false)

  useEffect(() => {
    if (!enabled) return
    listSkills({ page: 1, page_size: 100, is_enabled: true })
      .then((p) => setItems(p.items))
      .catch((e) => toast.error(errorText(e, '加载技能失败')))
      .finally(() => setLoaded(true))
  }, [enabled])

  return { items, loaded }
}
