import { useCallback, useEffect, useMemo, useState } from 'react'
import { Button, Grid, Select, Typography, message } from 'antd'
import { MessageOutlined, PlusOutlined } from '@ant-design/icons'
import { chatAgentStream, deleteConversation, getConversation, listAvailableAgents, listConversations, listMessages, OPTIONS_PAGE, type AgentBrief, type ChatTransport, type ConversationRow } from '../api'
import { visibleNavItems } from '../constants/nav'
import { useQueryState } from '../hooks/useQueryState'
import { useAuth } from '../store/auth'
import ChatPanel from '../components/chat/ChatPanel'
import ConversationList from '../components/chat/ConversationList'
import { useChatStream } from '../components/chat/useChatStream'
import { toChatMessages } from '../components/chat/messages'
import { CHAT_MESSAGE_MAX_CHARS, FULL_CAPABILITIES, type ChatCapabilities, type Msg } from '../components/chat/types'
import { errorText } from '../utils/errors'

const { useBreakpoint } = Grid
const PAGE = 50

// 聊天页：左侧按当前智能体过滤的会话列表 + 右侧对话面板（ChatPanel，与装配页调试、分享访客页共用）。
// 智能体与会话通过 ?agent= 与 ?conversation= 深链，可从智能体详情、运行详情跳入；发送走 SSE 流式接口（useChatStream + chatAgentStream）。
export default function Chat() {
  const screens = useBreakpoint()
  const isMobile = !screens.md
  const [query, setQuery] = useQueryState<{ agent?: string; conversation?: string }>({ agent: undefined, conversation: undefined })
  const agentId = query.agent ? Number(query.agent) : undefined
  const conversationId = query.conversation ? Number(query.conversation) : null
  const [agents, setAgents] = useState<AgentBrief[]>([])
  const role = useAuth((s) => s.user?.role)
  const canManageAgents = visibleNavItems(role).some((item) => item.key === '/agents')
  // docs/15 D-19：admin / developer 全部可见；调用者不看运行记录链接（无权访问）与工具入参和结果（可能含内部地址）
  const canViewRuns = visibleNavItems(role).some((item) => item.key === '/runs')
  const capabilities = useMemo<ChatCapabilities>(() => (canViewRuns ? FULL_CAPABILITIES : { ...FULL_CAPABILITIES, showRunLink: false, showToolDetails: false }), [canViewRuns])
  const [conversations, setConversations] = useState<ConversationRow[]>([])
  const [total, setTotal] = useState(0)
  const [q, setQ] = useState<string | undefined>()
  const [messages, setMessages] = useState<Msg[]>([])
  const [loadingMessages, setLoadingMessages] = useState(false)
  const [showList, setShowList] = useState(false)

  // 可对话列表只含已发布的智能体，所有角色都能取（管理用的 /agents 列表 caller 无权访问）。
  // URL 没带智能体时：带了会话就按会话定智能体（落到第一个的话接着发送会被 404 拒绝），都没带默认第一个
  useEffect(() => {
    listAvailableAgents(OPTIONS_PAGE)
      .then(async (p) => {
        setAgents(p.items)
        if (agentId) return
        const patch: { agent?: string; conversation?: string } = { agent: p.items[0] ? String(p.items[0].id) : undefined }
        if (conversationId) {
          try {
            const conv = await getConversation(conversationId)
            if (conv.agent_id) patch.agent = String(conv.agent_id)
          } catch (e) {
            message.error(errorText(e, '会话不存在或已删除'))
            patch.conversation = undefined
          }
        }
        setQuery(patch)
      })
      .catch((e) => message.error(errorText(e, '加载智能体失败')))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const loadConversations = useCallback(async (page = 1) => {
    if (!agentId) return
    try {
      const res = await listConversations({ agent_id: agentId, q, page, page_size: PAGE })
      setConversations((prev) => (page === 1 ? res.items : [...prev, ...res.items]))
      setTotal(res.total)
    } catch (e) { message.error(errorText(e, '加载会话失败')) }
  }, [agentId, q])
  useEffect(() => { loadConversations(1) }, [loadConversations])

  // 切换会话：拉取历史并归一化成对话面板的消息结构；切走时先清空避免露出旧内容
  useEffect(() => {
    if (!conversationId) { setMessages([]); return }
    let cancelled = false
    setMessages([])
    setLoadingMessages(true)
    listMessages(conversationId)
      .then((rows) => { if (!cancelled) setMessages(toChatMessages(rows)) })
      .catch((e) => { if (!cancelled) message.error(errorText(e, '加载历史失败')) })
      .finally(() => { if (!cancelled) setLoadingMessages(false) })
    return () => { cancelled = true }
  }, [conversationId])

  const transport = useMemo<ChatTransport | undefined>(
    () => (agentId ? (payload, handlers, signal) => chatAgentStream(agentId, payload, handlers, signal) : undefined),
    [agentId],
  )
  const stream = useChatStream(messages, setMessages, {
    transport, conversationId,
    onConversationCreated: (id) => { setQuery({ conversation: String(id) }); loadConversations(1) },
  })
  const currentAgent = useMemo(() => agents.find((a) => a.id === agentId), [agents, agentId])

  const agentSelector = (
    <Select
      placeholder="选择已发布的智能体" style={{ width: '100%' }} value={agentId} showSearch optionFilterProp="label"
      onChange={(v) => { setQuery({ agent: String(v), conversation: undefined }); setMessages([]) }}
      options={agents.map((a) => ({ value: a.id, label: a.name }))}
      notFoundContent={<Typography.Text type="secondary">{canManageAgents ? '没有已发布的智能体，先去智能体页发布一个' : '还没有可用的智能体，请联系管理员发布'}</Typography.Text>}
    />
  )
  const newConversation = () => { setQuery({ conversation: undefined }); setMessages([]); setShowList(false) }
  const removeConversation = async (id: number) => {
    await deleteConversation(id)
    if (conversationId === id) newConversation()
    loadConversations(1)
  }

  const sidebar = (
    <div style={{ width: isMobile ? '100%' : 236, border: '1px solid #e5e7eb', borderRadius: 8, padding: 12, flexShrink: 0, height: '100%', minHeight: 0, background: '#fff' }}>
      <ConversationList
        conversations={conversations} total={total} currentId={conversationId} q={q} onSearch={setQ}
        onSelect={(id) => { setQuery({ conversation: String(id) }); setShowList(false) }}
        onNew={newConversation}
        onLoadMore={() => loadConversations(Math.floor(conversations.length / PAGE) + 1)}
        onDelete={removeConversation}
        agentSelector={agentSelector}
      />
    </div>
  )

  const header = (
    <>
      {isMobile && <Button size="small" icon={<MessageOutlined />} onClick={() => setShowList(true)}>会话</Button>}
      <div style={{ flex: 1, minWidth: 0 }}>
        <Typography.Text strong>{currentAgent?.name ?? '未选择智能体'}</Typography.Text>
        {currentAgent?.description && <Typography.Text type="secondary" style={{ marginLeft: 8, fontSize: 12 }}>{currentAgent.description}</Typography.Text>}
      </div>
      {isMobile && <Button size="small" icon={<PlusOutlined />} onClick={newConversation} />}
    </>
  )
  const chatArea = (
    <ChatPanel
      header={header} messages={messages} sending={stream.sending} loading={loadingMessages} isMobile={isMobile}
      emptyHint={currentAgent ? `向「${currentAgent.name}」发送第一条消息开始对话` : '先在左侧选择一个已发布的智能体'}
      inputDisabled={!agentId} maxLength={CHAT_MESSAGE_MAX_CHARS} capabilities={capabilities}
      onSend={stream.send} onStop={stream.stop} onRegenerate={stream.regenerate}
    />
  )

  if (isMobile) return <div style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column' }}>{showList ? sidebar : chatArea}</div>
  return <div style={{ display: 'flex', flex: 1, gap: 12, minHeight: 0 }}>{sidebar}{chatArea}</div>
}
