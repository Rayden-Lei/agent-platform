import { useState } from 'react'
import { Drawer, Grid } from 'antd'
import { useParams } from 'react-router-dom'
import { useShareAccess } from '../hooks/useShareAccess'
import { useShareChat } from '../hooks/useShareChat'
import { useVisualViewportHeight } from '../hooks/useVisualViewportHeight'
import ChatPanel from '../components/chat/ChatPanel'
import ConversationList from '../components/chat/ConversationList'
import { CHAT_MESSAGE_MAX_CHARS } from '../components/chat/types'
import ShareHeader from '../components/share/ShareHeader'
import SharePasswordForm from '../components/share/SharePasswordForm'
import ShareStatus from '../components/share/ShareStatus'

const { useBreakpoint } = Grid

// 分享访客页 /s/:code（docs/15 3.6，PB-01）：不进 AppLayout、不需要平台登录（"仅登录"模式除外）。
// 进入流程（资料、访问密码、领访客令牌、状态页）在 useShareAccess，会话与发送在 useShareChat；本页只做编排。
// 对话复用 ChatPanel，按"最少暴露"给能力：不显示运行记录、Token、工具入参与结果，引用按链接设置。消息区是唯一滚动区。
export default function SharePage() {
  const { code = '' } = useParams()
  const isMobile = !useBreakpoint().md
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
    <div style={{ height: viewportHeight ? `${viewportHeight}px` : '100%', display: 'flex', flexDirection: 'column', overflow: 'hidden', background: '#f5f7fa', paddingTop: 'env(safe-area-inset-top)', boxSizing: 'border-box' }}>
      <div style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column', width: '100%', maxWidth: 960, margin: '0 auto', padding: isMobile ? 0 : 16 }}>
        <ChatPanel
          header={<ShareHeader name={info.agent_name} description={info.description} onOpenList={() => setListOpen(true)} onNew={newConversation} />}
          messages={chat.messages} sending={chat.stream.sending} loading={chat.loadingMessages} isMobile={isMobile}
          emptyHint={`向「${info.agent_name}」提问，开始对话`} maxLength={CHAT_MESSAGE_MAX_CHARS}
          capabilities={{ showCitations: info.show_citations }}
          onSend={chat.stream.send} onStop={chat.stream.stop} onRegenerate={chat.stream.regenerate}
        />
      </div>
      <Drawer title="我的会话" placement="left" width={isMobile ? '85%' : 300} open={listOpen} onClose={() => setListOpen(false)} styles={{ body: { padding: 12 } }}>
        <ConversationList
          conversations={chat.conversations} total={chat.total} currentId={chat.conversationId} q={chat.q} onSearch={chat.setQ}
          onSelect={(id) => { chat.setConversationId(id); setListOpen(false) }}
          onNew={newConversation} onLoadMore={chat.loadMore} onDelete={chat.removeConversation} agentSelector={null}
        />
      </Drawer>
    </div>
  )
}
