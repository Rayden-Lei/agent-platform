import { useEffect, useRef, useState } from 'react'
import { Select, Input, Button, message, List, Empty, Popconfirm, Grid } from 'antd'
import { SendOutlined, PlusOutlined, DeleteOutlined, StopOutlined, ReloadOutlined, MessageOutlined } from '@ant-design/icons'
import { useLocation } from 'react-router-dom'
import { listAgents, listConversations, listMessages, deleteConversation, chatAgentStream, OPTIONS_PAGE } from '../api'
import AssistantMessage from '../components/chat/AssistantMessage'
import type { Msg, ToolStep } from '../components/chat/types'

const { useBreakpoint } = Grid

export default function Chat() {
  const location = useLocation()
  const screens = useBreakpoint()
  const isMobile = !screens.md
  const [agents, setAgents] = useState<any[]>([])
  const [agentId, setAgentId] = useState<number | undefined>(location.state?.agentId)
  const [conversations, setConversations] = useState<any[]>([])
  const [conversationId, setConversationId] = useState<number | null>(null)
  const [messages, setMessages] = useState<Msg[]>([])
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [showList, setShowList] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)
  const abortRef = useRef<AbortController | null>(null)

  const loadAgents = async () => {
    try {
      const list = (await listAgents({ status: 'published', ...OPTIONS_PAGE })).items
      setAgents(list)
      if (list.length > 0) setAgentId((prev) => prev ?? list[0].id)
    } catch (e: any) { message.error(e.response?.data?.detail || '加载智能体失败') }
  }
  const loadConversations = async () => {
    try { setConversations((await listConversations(OPTIONS_PAGE)).items) } catch (e: any) { message.error(e.response?.data?.detail || '加载会话失败') }
  }
  useEffect(() => { loadAgents(); loadConversations() }, [])

  const scrollBottom = () => bottomRef.current?.scrollIntoView({ behavior: 'smooth' })

  const selectConversation = async (cid: number) => {
    setConversationId(cid)
    setShowList(false)
    try {
      const msgs: any = await listMessages(cid)
      setMessages(msgs.map((m: any): Msg => ({
        role: m.role,
        content: m.content,
        citations: m.citations || [],
        tools: (m.tool_calls || []).map((t: any): ToolStep => ({
          id: t.id,
          name: t.name,
          args: t.args ?? t.arguments ?? {},
          status: 'done',
          result: t.result,
        })),
        usage: m.token_usage || undefined,
      })))
    } catch { message.error('加载历史失败') }
  }

  const newConversation = () => {
    setConversationId(null)
    setMessages([])
    setShowList(false)
  }

  // 更新流式过程中最后一条 assistant 消息（浅拷贝后原地修改，保持不可变更新语义）
  const patchLast = (fn: (last: Msg) => void) => {
    setMessages((prev) => {
      if (prev.length === 0) return prev
      const next = [...prev]
      const last = { ...next[next.length - 1] }
      fn(last)
      next[next.length - 1] = last
      return next
    })
  }

  const doSend = async (msg: string, isRegen: boolean) => {
    if (!msg || !agentId || sending) return
    if (isRegen) {
      setMessages((prev) => { const next = [...prev]; next.pop(); next.push({ role: 'assistant', content: '' }); return next })
    } else {
      setMessages((prev) => [...prev, { role: 'user', content: msg }, { role: 'assistant', content: '' }])
      setInput('')
    }
    setSending(true)
    const controller = new AbortController()
    abortRef.current = controller

    try {
      const newCid = await chatAgentStream(agentId, { message: msg, conversation_id: conversationId }, {
        onCitations: (citations) => patchLast((last) => { last.citations = citations }),
        onDelta: (content) => patchLast((last) => { last.content += content }),
        onToolCall: (tc) => patchLast((last) => {
          last.tools = [...(last.tools || []), { id: tc.id, name: tc.name || '工具', args: tc.arguments ?? {}, status: 'running' as const }]
        }),
        onToolResult: (tr) => patchLast((last) => {
          const tools = last.tools || []
          let idx = tools.findIndex((t) => t.id && tr.tool_call_id && t.id === tr.tool_call_id)
          if (idx < 0) idx = tools.findIndex((t) => t.status === 'running')
          if (idx >= 0) {
            const next = tools.slice()
            next[idx] = { ...next[idx], status: 'done' as const, result: tr.content }
            last.tools = next
          }
        }),
        onError: (errMsg) => patchLast((last) => { last.content += '\n[错误] ' + errMsg }),
        onDone: (evt) => patchLast((last) => { if (evt.usage) last.usage = evt.usage }),
      }, controller.signal)
      if (newCid && newCid !== conversationId) { setConversationId(newCid); loadConversations() }
    } catch (e: any) {
      if (e.name === 'AbortError') return
      message.error(e.message || '发送失败')
    } finally {
      setSending(false)
      abortRef.current = null
      scrollBottom()
    }
  }

  const send = () => {
    if (!agentId) { message.error('请先选择智能体'); return }
    if (!input.trim()) return
    doSend(input.trim(), false)
  }
  const stop = () => { abortRef.current?.abort() }
  const regenerate = () => {
    const lastUser = [...messages].reverse().find((m) => m.role === 'user')
    if (lastUser) doSend(lastUser.content, true)
  }

  const agentSelector = (
    <Select
      placeholder="选择智能体"
      style={{ width: '100%' }}
      value={agentId}
      onChange={(v) => { setAgentId(v); newConversation() }}
      options={agents.map((a: any) => ({ value: a.id, label: a.name }))}
    />
  )

  const conversationList = (
    <div style={{ width: isMobile ? '100%' : 220, border: '1px solid #e5e7eb', borderRadius: 8, padding: 12, display: 'flex', flexDirection: 'column', flexShrink: 0, height: '100%', minHeight: 0 }}>
      <div style={{ marginBottom: 8 }}>{agentSelector}</div>
      <Button type="primary" icon={<PlusOutlined />} block onClick={newConversation} style={{ marginBottom: 8 }}>新对话</Button>
      <div style={{ flex: 1, overflow: 'auto' }}>
        {conversations.length === 0 ? (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无会话" />
        ) : (
          <List
            size="small"
            dataSource={conversations}
            renderItem={(c: any) => (
              <List.Item
                onClick={() => selectConversation(c.id)}
                style={{ cursor: 'pointer', background: conversationId === c.id ? '#e8eefb' : 'transparent', padding: '6px 8px', borderRadius: 6 }}
                actions={[
                  <Popconfirm key="d" title="删除会话？" onConfirm={async (e) => { e?.stopPropagation(); await deleteConversation(c.id); if (conversationId === c.id) newConversation(); loadConversations() }}>
                    <DeleteOutlined onClick={(e) => e.stopPropagation()} />
                  </Popconfirm>,
                ]}
              >
                <div style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontSize: 13 }}>{c.title || '对话'}</div>
              </List.Item>
            )}
          />
        )}
      </div>
    </div>
  )

  const chatArea = (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', border: '1px solid #e5e7eb', borderRadius: 8, minWidth: 0, minHeight: 0 }}>
      {isMobile && (
        <div style={{ padding: '8px 12px', borderBottom: '1px solid #e5e7eb', display: 'flex', alignItems: 'center', gap: 8, flexShrink: 0 }}>
          <Button size="small" icon={<MessageOutlined />} onClick={() => setShowList(true)}>会话</Button>
          <div style={{ flex: 1 }}>{agentSelector}</div>
          <Button size="small" icon={<PlusOutlined />} onClick={newConversation} />
        </div>
      )}
      <div style={{ flex: 1, overflow: 'auto', padding: isMobile ? 12 : 16, background: '#f5f6f8', minHeight: 0 }}>
        {messages.length === 0 && <Empty style={{ marginTop: 60 }} description="选择一个智能体开始对话" />}
        {messages.map((m, i) => {
          const isStreaming = i === messages.length - 1 && sending && m.role === 'assistant'
          return (
            <div key={i} style={{ display: 'flex', justifyContent: m.role === 'user' ? 'flex-end' : 'flex-start', marginBottom: 12 }}>
              {m.role === 'user' ? (
                <div style={{ maxWidth: isMobile ? '88%' : '75%', padding: '10px 14px', borderRadius: 8, background: '#1e40af', color: '#fff', whiteSpace: 'pre-wrap' }}>{m.content}</div>
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
      <div style={{ display: 'flex', gap: 8, padding: isMobile ? 8 : 12, borderTop: '1px solid #e5e7eb', flexShrink: 0, background: '#fff' }}>
        <Input.TextArea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onPressEnter={(e) => { if (!e.shiftKey) { e.preventDefault(); send() } }}
          placeholder="输入消息，Enter 发送"
          autoSize={{ minRows: 1, maxRows: 4 }}
        />
        {sending ? (
          <Button danger icon={<StopOutlined />} onClick={stop}>停止</Button>
        ) : (
          <Button type="primary" icon={<SendOutlined />} onClick={send}>发送</Button>
        )}
        {messages.some((m) => m.role === 'user') && !sending && !isMobile && (
          <Button icon={<ReloadOutlined />} onClick={regenerate}>重新生成</Button>
        )}
      </div>
    </div>
  )

  if (isMobile) {
    return (
      <div style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column' }}>
        {showList ? conversationList : chatArea}
      </div>
    )
  }

  return (
    <div style={{ display: 'flex', flex: 1, gap: 12, minHeight: 0 }}>
      {conversationList}
      {chatArea}
    </div>
  )
}
