import { useEffect, useRef } from 'react'
import AssistantMessage from './AssistantMessage'
import type { ChatCapabilities, Msg } from './types'
import { fromNow } from '../../utils/time'

// 消息流：用户消息右对齐实色块，助手消息平铺不套气泡；新消息到达自动滚到底。
interface Props {
  messages: Msg[]
  sending: boolean
  isMobile: boolean
  loading?: boolean
  emptyHint: string
  capabilities: ChatCapabilities
  agentName?: string
  onShowDetails?: (msg: Msg) => void
  onRegenerate?: () => void
}

export default function MessageList({ messages, sending, isMobile, loading, emptyHint, capabilities, agentName, onShowDetails, onRegenerate }: Props) {
  const bottomRef = useRef<HTMLDivElement>(null)
  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [messages.length, sending])

  return (
    <div
      className="flex-1 overflow-auto flex flex-col gap-5"
      style={{ padding: isMobile ? '14px 13px' : '20px 22px', minHeight: 0 }}
    >
      {messages.length === 0 && !loading && (
        <div className="flex-1 flex items-center justify-center">
          <div className="text-center max-w-sm text-[13px]" style={{ color: 'var(--fg-subtle)' }}>{emptyHint}</div>
        </div>
      )}
      {loading && messages.length === 0 && (
        <div className="flex flex-col gap-3">
          {[0, 1, 2].map((i) => (
            <span key={i} className="block h-3 rounded" style={{ background: 'var(--bg-soft)', width: i === 1 ? '72%' : '88%' }} />
          ))}
        </div>
      )}

      {messages.map((m, i) => {
        // 只有"最后一条且正在发送中的 assistant 消息"才算流式中，驱动脉冲与占位文案
        const isStreaming = i === messages.length - 1 && sending && m.role === 'assistant'
        // key 用索引，不用 m.id：流式时 assistant 还没有 id（key=i），流结束时 onDone 赋上真实 id（key=160），
        // React 会把整棵子树当成新组件重挂 —— Markdown 重新解析重排，肉眼就是"回答完闪一下"。
        // 消息只会在尾部追加 / 替换最后一条 / 整体清空重载，索引始终稳定。
        if (m.role === 'user') {
          return (
            <div key={i} className="flex flex-col items-end gap-1">
              <div
                className="whitespace-pre-wrap text-[14px] leading-[1.7]"
                style={{
                  maxWidth: isMobile ? '90%' : '76%',
                  padding: '9px 13px',
                  borderRadius: 'var(--radius)',
                  background: 'var(--accent)',
                  color: 'var(--accent-fg)',
                }}
              >
                {m.content}
              </div>
              {m.createdAt && <span className="text-[11px]" style={{ color: 'var(--fg-subtle)' }}>{fromNow(m.createdAt)}</span>}
            </div>
          )
        }
        return (
          <div key={i} style={{ maxWidth: isMobile ? '100%' : '88%' }}>
            <AssistantMessage
              msg={m}
              streaming={isStreaming}
              capabilities={capabilities}
              onShowDetails={onShowDetails}
              agentName={agentName}
              onRegenerate={isStreaming ? undefined : onRegenerate}
            />
          </div>
        )
      })}
      <div ref={bottomRef} />
    </div>
  )
}
