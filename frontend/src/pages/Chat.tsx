import { useCallback, useEffect, useMemo, useState } from 'react'
import { Button, Grid, Select, Typography, message } from 'antd'
import { MessageOutlined, PlusOutlined } from '@ant-design/icons'
import { listAgents, listConversations, listMessages, OPTIONS_PAGE, type AgentRow, type ConversationRow } from '../api'
import { useQueryState } from '../hooks/useQueryState'
import ConversationList from '../components/chat/ConversationList'
import MessageList from '../components/chat/MessageList'
import ChatInput from '../components/chat/ChatInput'
import { useChatStream } from '../components/chat/useChatStream'
import type { Msg, ToolStep } from '../components/chat/types'
import { errorText } from '../utils/errors'

const { useBreakpoint } = Grid
const PAGE = 50

// 聊天页：左侧按当前智能体过滤的会话列表 + 右侧消息流。智能体与会话通过 ?agent= 与 ?conversation= 深链，
// 可从智能体详情、运行详情跳入；发送走 SSE 流式接口（useChatStream）。
export default function Chat() {
  const screens = useBreakpoint()
  const isMobile = !screens.md
  const [query, setQuery] = useQueryState<{ agent?: string; conversation?: string }>({ agent: undefined, conversation: undefined })
  const agentId = query.agent ? Number(query.agent) : undefined
  const conversationId = query.conversation ? Number(query.conversation) : null
  const [agents, setAgents] = useState<AgentRow[]>([])
  const [conversations, setConversations] = useState<ConversationRow[]>([])
  const [total, setTotal] = useState(0)
  const [q, setQ] = useState<string | undefined>()
  const [messages, setMessages] = useState<Msg[]>([])
  const [loadingMessages, setLoadingMessages] = useState(false)
  const [showList, setShowList] = useState(false)

  // 只展示已发布的智能体；URL 没指定时默认第一个
  useEffect(() => {
    listAgents({ status: 'published', ...OPTIONS_PAGE })
      .then((p) => { setAgents(p.items); if (!agentId && p.items.length) setQuery({ agent: String(p.items[0].id) }) })
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

  // 切换会话：拉取历史并归一化成 Msg（tool_calls → tools、token_usage → usage）；切走时先清空避免露出旧内容
  useEffect(() => {
    if (!conversationId) { setMessages([]); return }
    let cancelled = false
    setMessages([])
    setLoadingMessages(true)
    listMessages(conversationId)
      .then((rows) => {
        if (cancelled) return
        setMessages(rows.map((m): Msg => ({
          id: m.id, role: m.role as Msg['role'], content: m.content, citations: (m.citations as Msg['citations']) || [],
          tools: ((m.tool_calls || []) as Array<{ id?: string; name: string; args?: unknown; arguments?: unknown; result?: string }>).map((t): ToolStep => ({ id: t.id, name: t.name, args: t.args ?? t.arguments ?? {}, status: 'done', result: t.result })),
          usage: m.token_usage || undefined, createdAt: m.created_at,
        })))
      })
      .catch((e) => { if (!cancelled) message.error(errorText(e, '加载历史失败')) })
      .finally(() => { if (!cancelled) setLoadingMessages(false) })
    return () => { cancelled = true }
  }, [conversationId])

  const stream = useChatStream(messages, setMessages, {
    agentId, conversationId,
    onConversationCreated: (id) => { setQuery({ conversation: String(id) }); loadConversations(1) },
  })
  const currentAgent = useMemo(() => agents.find((a) => a.id === agentId), [agents, agentId])

  const agentSelector = (
    <Select
      placeholder="选择已发布的智能体" style={{ width: '100%' }} value={agentId} showSearch optionFilterProp="label"
      onChange={(v) => { setQuery({ agent: String(v), conversation: undefined }); setMessages([]) }}
      options={agents.map((a) => ({ value: a.id, label: a.name }))}
      notFoundContent={<Typography.Text type="secondary">没有已发布的智能体，先去智能体页发布一个</Typography.Text>}
    />
  )
  const newConversation = () => { setQuery({ conversation: undefined }); setMessages([]); setShowList(false) }

  const sidebar = (
    <div style={{ width: isMobile ? '100%' : 236, border: '1px solid #e5e7eb', borderRadius: 8, padding: 12, flexShrink: 0, height: '100%', minHeight: 0, background: '#fff' }}>
      <ConversationList
        conversations={conversations} total={total} currentId={conversationId} q={q} onSearch={setQ}
        onSelect={(id) => { setQuery({ conversation: String(id) }); setShowList(false) }}
        onNew={newConversation}
        onLoadMore={() => loadConversations(Math.floor(conversations.length / PAGE) + 1)}
        onDeleted={(id) => { if (conversationId === id) newConversation(); loadConversations(1) }}
        agentSelector={agentSelector}
      />
    </div>
  )

  const chatArea = (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', border: '1px solid #e5e7eb', borderRadius: 8, minWidth: 0, minHeight: 0, background: '#fff' }}>
      <div style={{ padding: '8px 12px', borderBottom: '1px solid #e5e7eb', display: 'flex', alignItems: 'center', gap: 8, flexShrink: 0 }}>
        {isMobile && <Button size="small" icon={<MessageOutlined />} onClick={() => setShowList(true)}>会话</Button>}
        <div style={{ flex: 1, minWidth: 0 }}>
          <Typography.Text strong>{currentAgent?.name ?? '未选择智能体'}</Typography.Text>
          {currentAgent?.description && <Typography.Text type="secondary" style={{ marginLeft: 8, fontSize: 12 }}>{currentAgent.description}</Typography.Text>}
          {currentAgent && <Typography.Text type="secondary" style={{ marginLeft: 8, fontSize: 12 }}>模型 {currentAgent.model_name || '-'}{currentAgent.kb_ids?.length ? ` · 知识库 ${currentAgent.kb_ids.length}` : ''}{currentAgent.tool_ids?.length ? ` · 工具 ${currentAgent.tool_ids.length}` : ''}</Typography.Text>}
        </div>
        {isMobile && <Button size="small" icon={<PlusOutlined />} onClick={newConversation} />}
      </div>
      <MessageList messages={messages} sending={stream.sending} isMobile={isMobile} loading={loadingMessages} emptyHint={currentAgent ? `向「${currentAgent.name}」发送第一条消息开始对话` : '先在左侧选择一个已发布的智能体'} />
      <ChatInput disabled={!agentId} sending={stream.sending} canRegenerate={messages.some((m) => m.role === 'user')} onSend={stream.send} onStop={stream.stop} onRegenerate={stream.regenerate} compact={isMobile} />
    </div>
  )

  if (isMobile) return <div style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column' }}>{showList ? sidebar : chatArea}</div>
  return <div style={{ display: 'flex', flex: 1, gap: 12, minHeight: 0 }}>{sidebar}{chatArea}</div>
}
