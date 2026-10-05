import { useEffect, useRef, useState } from 'react'
import { message } from 'antd'
import { getAvailableAgent, listAvailableAgents, OPTIONS_PAGE, type AgentBrief } from '../api'
import { errorText } from '../utils/errors'

// 对话页的可对话智能体下拉（docs/15 AG-05）：首屏取一页（100 个）；超过一页时改为服务端按名称搜索（300ms 防抖），
// 此前只能在前 100 个里挑；深链指向的智能体不在已加载的选项里时单独取一次，未发布 / 已下线时提示原因。
export function useAvailableAgents(selectedId?: number) {
  const [agents, setAgents] = useState<AgentBrief[]>([])
  const [loaded, setLoaded] = useState(false)
  const [remote, setRemote] = useState(false) // 总数超过一页：前端只有部分选项，搜索必须走服务端
  const [search, setSearch] = useState('')
  const lastSearch = useRef('')
  const seq = useRef(0)

  useEffect(() => {
    listAvailableAgents(OPTIONS_PAGE)
      .then((p) => { setAgents(p.items); setRemote(p.total > p.items.length) })
      .catch((e) => message.error(errorText(e, '加载智能体失败')))
      .finally(() => setLoaded(true))
  }, [])

  // 服务端搜索：请求序号丢掉过期响应；当前选中的那个始终留在选项里（不然下拉里会显示成一个数字）
  useEffect(() => {
    if (!remote || search === lastSearch.current) return
    lastSearch.current = search
    const mine = ++seq.current
    const handle = setTimeout(() => {
      listAvailableAgents({ ...OPTIONS_PAGE, q: search || undefined })
        .then((p) => { if (mine === seq.current) setAgents((prev) => keepSelected(p.items, prev, selectedId)) })
        .catch((e) => message.error(errorText(e, '搜索智能体失败')))
    }, 300)
    return () => clearTimeout(handle)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search, remote])

  useEffect(() => {
    if (!loaded || !selectedId || agents.some((a) => a.id === selectedId)) return
    getAvailableAgent(selectedId)
      .then((a) => setAgents((prev) => (prev.some((x) => x.id === a.id) ? prev : [a, ...prev])))
      .catch((e) => message.error(errorText(e, '这个智能体当前不可用')))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loaded, selectedId])

  return { agents, loaded, remote, onSearch: setSearch }
}

function keepSelected(items: AgentBrief[], prev: AgentBrief[], selectedId?: number): AgentBrief[] {
  if (!selectedId || items.some((a) => a.id === selectedId)) return items
  const current = prev.find((a) => a.id === selectedId)
  return current ? [current, ...items] : items
}
