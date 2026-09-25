import type { ReactNode } from 'react'
import ChatInput from './ChatInput'
import MessageList from './MessageList'
import { MINIMAL_CAPABILITIES, type ChatCapabilities, type Msg } from './types'

// 对话面板：头部插槽 + 消息流 + 输入条。登录对话页、装配页的调试面板、分享访客页共用（docs/15 FR-044）。
// 不发请求：消息与发送由调用方注入（页面取数 + useChatStream）；能看到哪些过程信息由 capabilities 决定，没传的项按"最少暴露"
interface Props {
  header?: ReactNode
  messages: Msg[]
  sending: boolean
  loading?: boolean
  emptyHint: string
  isMobile: boolean
  inputDisabled?: boolean
  inputPlaceholder?: string
  maxLength?: number
  capabilities?: Partial<ChatCapabilities>
  onSend: (text: string) => void
  onStop: () => void
  onRegenerate: () => void
}

export default function ChatPanel({ header, messages, sending, loading, emptyHint, isMobile, inputDisabled, inputPlaceholder, maxLength, capabilities, onSend, onStop, onRegenerate }: Props) {
  const caps = { ...MINIMAL_CAPABILITIES, ...capabilities }
  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', border: '1px solid #e5e7eb', borderRadius: 8, minWidth: 0, minHeight: 0, background: '#fff' }}>
      {header && (
        <div style={{ padding: '8px 12px', borderBottom: '1px solid #e5e7eb', display: 'flex', alignItems: 'center', gap: 8, flexShrink: 0 }}>{header}</div>
      )}
      <MessageList messages={messages} sending={sending} isMobile={isMobile} loading={loading} emptyHint={emptyHint} capabilities={caps} />
      <ChatInput
        disabled={inputDisabled} sending={sending} placeholder={inputPlaceholder} maxLength={maxLength} compact={isMobile}
        canRegenerate={caps.allowRegenerate && messages.some((m) => m.role === 'user')}
        onSend={onSend} onStop={onStop} onRegenerate={onRegenerate}
      />
    </div>
  )
}
