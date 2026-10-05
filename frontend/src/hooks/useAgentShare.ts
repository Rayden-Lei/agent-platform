import { useState } from 'react'
import { message } from 'antd'
import { getAgentShare, resetAgentShare, updateAgentShare, type AgentShare, type AgentShareInput } from '../api'
import { errorText } from '../utils/errors'
import { useAsyncData } from './useAsyncData'

// 智能体"发布渠道 → 分享链接"的取数（docs/15 3.6 前端取数分层）：读取、保存、重置都在这里，ShareLinkCard 只接收 props 与回调。
// 保存与重置返回的就是最新配置（含预检 warnings），直接替换本地数据，不再多查一次。
export function useAgentShare(agentId: number) {
  const { data: share, loading, error, reload, setData } = useAsyncData<AgentShare>(() => getAgentShare(agentId), [agentId], { errorText: '加载分享配置失败' })
  const [saving, setSaving] = useState(false)

  const save = async (input: AgentShareInput, okText = '已保存') => {
    setSaving(true)
    try {
      setData(await updateAgentShare(agentId, input))
      message.success(okText)
      return true
    } catch (e) {
      message.error(errorText(e, '保存分享配置失败'))
      return false
    } finally {
      setSaving(false)
    }
  }
  const reset = async () => {
    try {
      setData(await resetAgentShare(agentId))
      message.success('已换新链接：旧链接与已打开的访客立即失效')
    } catch (e) { message.error(errorText(e, '重置链接失败')) }
  }
  return { share, loading, error, reload, saving, save, reset }
}
