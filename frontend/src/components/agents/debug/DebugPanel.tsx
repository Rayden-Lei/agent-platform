import { useState } from 'react'
import { Button, Tooltip, Typography } from 'antd'
import { ClearOutlined, MenuUnfoldOutlined } from '@ant-design/icons'
import ChatPanel from '../../chat/ChatPanel'
import { CHAT_MESSAGE_MAX_CHARS, DEBUG_CAPABILITIES, type Msg } from '../../chat/types'
import DebugDetailDrawer from './DebugDetailDrawer'

// 装配页右栏的调试面板（docs/15 3.4，FR-041）：调试对象是编辑器当前内容（含未保存修改），不用保存就能试。
// 调试历史只在页面里、不进会话列表；运行记录记 source=debug，运营统计不计，模型消耗照常计入。
// 只接收 props 与回调：发送与流式状态在 hooks/useAgentDebug，由装配页注入（07 第 2、9 节）。
interface Props {
  messages: Msg[]
  sending: boolean
  compact: boolean
  onSend: (text: string) => void
  onStop: () => void
  onRegenerate: () => void
  onClear: () => void
  onCollapse?: () => void
}

export default function DebugPanel({ messages, sending, compact, onSend, onStop, onRegenerate, onClear, onCollapse }: Props) {
  const [detail, setDetail] = useState<Msg | null>(null)
  const header = (
    <>
      <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column' }}>
        <Typography.Text strong>调试 <Typography.Text type="secondary" style={{ fontSize: 12, fontWeight: 400 }}>对象：编辑器当前内容（含未保存修改）</Typography.Text></Typography.Text>
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>引用的工具、知识库、模型本身的修改不经发布，立即影响线上</Typography.Text>
      </div>
      <Tooltip title="清空调试记录，重新开始"><Button size="small" icon={<ClearOutlined />} disabled={sending || !messages.length} onClick={onClear} /></Tooltip>
      {onCollapse && <Tooltip title="收起调试区"><Button size="small" icon={<MenuUnfoldOutlined />} onClick={onCollapse} /></Tooltip>}
    </>
  )
  return (
    <>
      <ChatPanel header={header} messages={messages} sending={sending} isMobile={compact} maxLength={CHAT_MESSAGE_MAX_CHARS} capabilities={DEBUG_CAPABILITIES}
        emptyHint="改完左侧配置直接在这里提问，不用保存。每轮都真实调用模型（计入模型消耗），不进会话列表，运营统计不计。"
        onSend={onSend} onStop={onStop} onRegenerate={onRegenerate} onShowDetails={setDetail} />
      <DebugDetailDrawer msg={detail} onClose={() => setDetail(null)} />
    </>
  )
}
