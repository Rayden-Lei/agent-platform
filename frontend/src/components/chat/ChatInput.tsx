import { useState } from 'react'
import { Button, Input } from 'antd'
import { ReloadOutlined, SendOutlined, StopOutlined } from '@ant-design/icons'

// 输入条：Enter 发送、Shift+Enter 换行；发送中切换为"停止"；有历史时可"重新生成"。
// maxLength 与后端 CHAT_MESSAGE_MAX_CHARS 对齐只是体验，超长的权威拒绝在后端（422）。
// 移动端（docs/15 CH-14）：底部叠加安全区（手势条不压住输入框）；输入法组合中按回车是在确认候选词，不发送——
// rc-textarea 的 onPressEnter 不判断组合态，2026-10-05 前用拼音输入法按回车选词会把半截拼音发出去
interface Props {
  disabled?: boolean
  sending: boolean
  canRegenerate: boolean
  onSend: (text: string) => void
  onStop: () => void
  onRegenerate: () => void
  compact?: boolean
  placeholder?: string
  maxLength?: number
}

export default function ChatInput({ disabled, sending, canRegenerate, onSend, onStop, onRegenerate, compact, placeholder, maxLength }: Props) {
  const [text, setText] = useState('')
  const send = () => { if (!text.trim() || sending || disabled) return; onSend(text.trim()); setText('') }
  const pad = compact ? 8 : 12
  return (
    <div className="chat-input-bar" style={{ display: 'flex', gap: 8, padding: pad, paddingBottom: `calc(${pad}px + env(safe-area-inset-bottom))`, borderTop: '1px solid #e5e7eb', flexShrink: 0, background: '#fff' }}>
      <Input.TextArea
        value={text}
        disabled={disabled}
        onChange={(e) => setText(e.target.value)}
        onPressEnter={(e) => {
          // keyCode 229：部分浏览器（含 Safari）组合中的按键事件不带 isComposing
          if (e.nativeEvent.isComposing || e.keyCode === 229) return
          if (!e.shiftKey) { e.preventDefault(); send() }
        }}
        placeholder={placeholder ?? (disabled ? '请先选择已发布的智能体' : '输入消息，Enter 发送，Shift+Enter 换行')}
        maxLength={maxLength}
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
