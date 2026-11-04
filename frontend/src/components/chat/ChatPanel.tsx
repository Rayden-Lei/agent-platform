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
  agentName?: string
  modelName?: string
  onSend: (text: string) => void
  onStop: () => void
  onRegenerate: () => void
  onShowDetails?: (msg: Msg) => void
}

export default function ChatPanel({
  header, messages, sending, loading, emptyHint, isMobile, inputDisabled, inputPlaceholder,
  maxLength, capabilities, agentName, modelName, onSend, onStop, onRegenerate, onShowDetails,
}: Props) {
  const caps = { ...MINIMAL_CAPABILITIES, ...capabilities }
  return (
    <div
      className="flex-1 flex flex-col min-w-0 min-h-0 rounded-xl overflow-hidden"
      style={{ background: 'var(--bg-elev)', border: '1px solid var(--border)' }}
    >
      {header && (
        <div
          className="shrink-0 flex items-center gap-2 px-4"
          style={{ paddingTop: 10, paddingBottom: 10, borderBottom: '1px solid var(--border)' }}
        >
          {header}
        </div>
      )}
      <MessageList
        messages={messages}
        sending={sending}
        isMobile={isMobile}
        loading={loading}
        emptyHint={emptyHint}
        capabilities={caps}
        agentName={agentName}
        onShowDetails={onShowDetails}
        onRegenerate={caps.allowRegenerate ? onRegenerate : undefined}
      />
      <ChatInput
        disabled={inputDisabled}
        sending={sending}
        placeholder={inputPlaceholder}
        maxLength={maxLength}
        compact={isMobile}
        modelName={modelName}
        onSend={onSend}
        onStop={onStop}
      />
    </div>
  )
}
