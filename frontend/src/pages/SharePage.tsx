import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { Sheet, SheetContent, SheetHeader, SheetTitle } from '@/components/shadcn/sheet'
import { useShareAccess } from '../hooks/useShareAccess'
import { useShareChat } from '../hooks/useShareChat'
import { useVisualViewportHeight } from '../hooks/useVisualViewportHeight'
import ChatPanel from '../components/chat/ChatPanel'
import ConversationList from '../components/chat/ConversationList'
import { CHAT_MESSAGE_MAX_CHARS } from '../components/chat/types'
import ErrorBoundary from '../components/common/ErrorBoundary'
import ShareHeader from '../components/share/ShareHeader'
import SharePasswordForm from '../components/share/SharePasswordForm'
import ShareStatus from '../components/share/ShareStatus'

// 是否窄屏（原来用 antd 的 Grid.useBreakpoint）：只依赖 matchMedia，访客页不引入任何登录态依赖
function useIsMobile() {
  const [isMobile, setIsMobile] = useState(() => (typeof window === 'undefined' ? false : !window.matchMedia('(min-width: 768px)').matches))
  useEffect(() => {
    const mq = window.matchMedia('(min-width: 768px)')
    const onChange = () => setIsMobile(!mq.matches)
    mq.addEventListener('change', onChange)
    return () => mq.removeEventListener('change', onChange)
  }, [])
  return isMobile
}

// 分享访客页 /s/:code（docs/15 3.6，PB-01）：不进 AppLayout、不需要平台登录（"仅登录"模式除外）。
// 进入流程（资料、访问密码、领访客令牌、状态页）在 useShareAccess，会话与发送在 useShareChat；本页只做编排。
// 对话复用 ChatPanel，按"最少暴露"给能力：不显示运行记录、Token、工具入参与结果，引用按链接设置。消息区是唯一滚动区。
// 对话区块整体崩掉时的降级界面：访客页没有菜单与侧栏，必须给一个能自己恢复的出口
function ShareCrash() {
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-3 px-6 text-center">
      <p className="m-0 text-[13.5px]" style={{ color: 'var(--fg-muted)' }}>
        页面出了点问题，这条会话没能渲染出来
      </p>
      <button
        type="button"
        onClick={() => window.location.reload()}
        className="rounded-lg px-3 py-1.5 text-[13px]"
        style={{ background: 'var(--accent)', color: 'var(--accent-fg)' }}
      >
        刷新重试
      </button>
    </div>
  )
}

export default function SharePage() {
  const { code = '' } = useParams()
  const isMobile = useIsMobile()
  const access = useShareAccess(code)
  const ready = access.phase === 'ready'
  const chat = useShareChat(code, ready, access.reenter)
  const [listOpen, setListOpen] = useState(false)
  const viewportHeight = useVisualViewportHeight() // 手机键盘弹出时整页跟着缩，输入框贴在键盘上沿（CH-14）

  if (access.phase === 'password') {
    return <SharePasswordForm agentName={access.info?.agent_name} error={access.passwordError} submitting={access.entering} onSubmit={access.submitPassword} />
  }
  if (!ready || !access.info) return <ShareStatus phase={access.phase} message={access.errorMessage} onRetry={access.retry} onLogin={access.goLogin} />
  const info = access.info

  const newConversation = () => { chat.newConversation(); setListOpen(false) }
  return (
    <div
      className="box-border flex flex-col overflow-hidden bg-background"
      style={{ height: viewportHeight ? `${viewportHeight}px` : '100%', paddingTop: 'env(safe-area-inset-top)' }}
    >
      <div className="mx-auto flex w-full flex-1 flex-col" style={{ minHeight: 0, maxWidth: 960, padding: isMobile ? 0 : 16 }}>
        {/* 整块对话兜底：访客页没有侧栏与菜单，一旦整树被卸载就只剩白屏，连重进入口都没有。
            降级时给一句可操作的话与刷新按钮，而不是空白 */}
        <ErrorBoundary fallback={<ShareCrash />}>
          <ChatPanel
            header={<ShareHeader name={info.agent_name} description={info.description} onOpenList={() => setListOpen(true)} onNew={newConversation} />}
            messages={chat.messages} sending={chat.stream.sending} loading={chat.loadingMessages} isMobile={isMobile}
            emptyHint={`向「${info.agent_name}」提问，开始对话`} maxLength={CHAT_MESSAGE_MAX_CHARS}
            capabilities={{ showCitations: info.show_citations }}
            onSend={chat.stream.send} onStop={chat.stream.stop} onRegenerate={chat.stream.regenerate}
          />
        </ErrorBoundary>
      </div>

      {/* 会话列表：窄屏占 85% 宽，宽屏固定 300px；访客只会看到自己的会话 */}
      <Sheet open={listOpen} onOpenChange={(next) => { if (!next) setListOpen(false) }}>
        <SheetContent side="left" className={`gap-0 ${isMobile ? 'w-[85%]' : 'w-[300px] sm:max-w-[300px]'}`}>
          <SheetHeader className="border-b border-border px-4 py-3 pr-10">
            <SheetTitle className="text-[14px]">我的会话</SheetTitle>
          </SheetHeader>
          <div className="flex min-h-0 flex-1 flex-col overflow-auto p-3">
            <ConversationList
              conversations={chat.conversations} total={chat.total} currentId={chat.conversationId} q={chat.q} onSearch={chat.setQ}
              onSelect={(id) => { chat.setConversationId(id); setListOpen(false) }}
              onNew={newConversation} onLoadMore={chat.loadMore} onDelete={chat.removeConversation} agentSelector={null}
            />
          </div>
        </SheetContent>
      </Sheet>
    </div>
  )
}
