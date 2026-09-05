import { useEffect, useRef } from 'react'
import { Typography } from 'antd'
import AssistantMessage from './AssistantMessage'
import EmptyState from '../common/EmptyState'
import type { Msg } from './types'
import { fromNow } from '../../utils/time'

// 消息流：user 气泡 + assistant 组件；最后一条发送中的 assistant 消息按流式渲染；新消息到达自动滚到底。
interface Props {
  messages: Msg[]
  sending: boolean
  isMobile: boolean
  loading?: boolean
  emptyHint: string
}

export default function MessageList({ messages, sending, isMobile, loading, emptyHint }: Props) {
  const bottomRef = useRef<HTMLDivElement>(null)
  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [messages.length, sending])
  return (
    <div style={{ flex: 1, overflow: 'auto', padding: isMobile ? 12 : 16, background: '#f5f6f8', minHeight: 0 }}>
      {messages.length === 0 && !loading && <EmptyState description={emptyHint} image="default" />}
      {messages.map((m, i) => {
        // 只有"最后一条且正在发送中的 assistant 消息"才算流式中，驱动打字光标/加载态
        const isStreaming = i === messages.length - 1 && sending && m.role === 'assistant'
        return (
          <div key={m.id ?? i} style={{ display: 'flex', flexDirection: 'column', alignItems: m.role === 'user' ? 'flex-end' : 'flex-start', marginBottom: 12 }}>
            {m.role === 'user' ? (
              <>
                <div style={{ maxWidth: isMobile ? '88%' : '75%', padding: '10px 14px', borderRadius: 8, background: '#1e40af', color: '#fff', whiteSpace: 'pre-wrap' }}>{m.content}</div>
                {m.createdAt && <Typography.Text type="secondary" style={{ fontSize: 11, marginTop: 2 }}>{fromNow(m.createdAt)}</Typography.Text>}
              </>
            ) : (
              <div className="assistant-bubble" style={{ maxWidth: isMobile ? '94%' : '78%' }}>
                <AssistantMessage msg={m} streaming={isStreaming} />
              </div>
            )}
          </div>
        )
      })}
      <div ref={bottomRef} />
    </div>
  )
}
