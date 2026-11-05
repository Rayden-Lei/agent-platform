import { useLayoutEffect, useRef } from 'react'
import AssistantMessage from './AssistantMessage'
import type { ChatCapabilities, Msg } from './types'
import { fromNow } from '../../utils/time'

// 消息流：用户消息右对齐实色块，助手消息平铺不套气泡；新消息到达自动滚到底。
//
// 滚动策略（2026-11-05 修）：
// ① 用 layout effect 直接改 scrollTop，不用 scrollIntoView —— 后者带 behavior:'smooth' 时，
//    切进一个长会话会从顶部一路平滑滑到底，肉眼就是"所有聊天都要滚一遍"。
// ② 流式输出时回答高度一直在涨，只监听 messages.length 不够（长度没变、内容在变），
//    所以每次渲染都重新钉底，回答才不会顶到输入框下面。
// ③ 用户往上翻看历史时不抢滚动，回到底部附近才重新吸附。
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

// 距底部多少像素内算"还贴着底"：留一点余量，不然滚轮一格就掉出吸附
const STICK_THRESHOLD = 48

export default function MessageList({ messages, sending, isMobile, loading, emptyHint, capabilities, agentName, onShowDetails, onRegenerate }: Props) {
  const scrollRef = useRef<HTMLDivElement>(null)
  // 是否跟随底部；用户手动上滚后置 false，回到底部附近恢复
  const stickRef = useRef(true)
  // 首条消息指纹：换会话 / 重新加载历史时整批消息都换了，靠它判断"这是一次整体替换"
  const headRef = useRef('')
  const lenRef = useRef(0)

  const head = messages[0] ? messages[0].role + ':' + messages[0].content.slice(0, 20) : ''

  // 不用 deps 数组：内容增长（流式）不会改变 messages.length，必须每次渲染都检查
  useLayoutEffect(() => {
    const el = scrollRef.current
    if (!el) return
    if (head !== headRef.current) {
      headRef.current = head
      stickRef.current = true
    }
    if (messages.length !== lenRef.current) {
      const grew = messages.length > lenRef.current
      lenRef.current = messages.length
      // 自己刚发出一条消息：无论之前翻到哪儿都跟到底部
      if (grew && messages[messages.length - 1]?.role === 'user') stickRef.current = true
    }
    if (stickRef.current) el.scrollTop = el.scrollHeight
  })

  const onScroll = () => {
    const el = scrollRef.current
    if (!el) return
    stickRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < STICK_THRESHOLD
  }

  return (
    <div
      ref={scrollRef}
      onScroll={onScroll}
      className="flex-1 overflow-auto flex flex-col gap-4"
      style={{ padding: isMobile ? '12px 12px' : '16px 18px', minHeight: 0 }}
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
                className="whitespace-pre-wrap text-[13.5px] leading-[1.7]"
                style={{
                  maxWidth: isMobile ? '90%' : '76%',
                  padding: '8px 12px',
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
    </div>
  )
}
