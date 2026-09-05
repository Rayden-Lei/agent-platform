import { useState } from 'react'
import { Button, Input } from 'antd'
import { ReloadOutlined, SendOutlined, StopOutlined } from '@ant-design/icons'

// 输入条：Enter 发送、Shift+Enter 换行；发送中切换为"停止"；有历史时可"重新生成"。
interface Props {
  disabled?: boolean
  sending: boolean
  canRegenerate: boolean
  onSend: (text: string) => void
  onStop: () => void
  onRegenerate: () => void
  compact?: boolean
}

export default function ChatInput({ disabled, sending, canRegenerate, onSend, onStop, onRegenerate, compact }: Props) {
  const [text, setText] = useState('')
  const send = () => { if (!text.trim() || sending || disabled) return; onSend(text.trim()); setText('') }
  return (
    <div style={{ display: 'flex', gap: 8, padding: compact ? 8 : 12, borderTop: '1px solid #e5e7eb', flexShrink: 0, background: '#fff' }}>
      <Input.TextArea
        value={text}
        disabled={disabled}
        onChange={(e) => setText(e.target.value)}
        onPressEnter={(e) => { if (!e.shiftKey) { e.preventDefault(); send() } }}
        placeholder={disabled ? '请先选择已发布的智能体' : '输入消息，Enter 发送，Shift+Enter 换行'}
        autoSize={{ minRows: 1, maxRows: 4 }}
      />
      {sending ? (
        <Button danger icon={<StopOutlined />} onClick={onStop}>停止</Button>
      ) : (
        <Button type="primary" icon={<SendOutlined />} disabled={disabled} onClick={send}>发送</Button>
      )}
      {canRegenerate && !sending && <Button icon={<ReloadOutlined />} onClick={onRegenerate} title="基于最后一条用户消息重新生成">{compact ? '' : '重新生成'}</Button>}
    </div>
  )
}
