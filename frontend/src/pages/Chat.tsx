import { useEffect, useRef, useState } from 'react'
import { Select, Input, Button, Tag, message, List, Empty, Popconfirm, Space } from 'antd'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { SendOutlined, PlusOutlined, DeleteOutlined, StopOutlined, ReloadOutlined } from '@ant-design/icons'
import { useLocation } from 'react-router-dom'
import { listAgents, listConversations, listMessages, deleteConversation } from '../api'

interface Msg {
  role: 'user' | 'assistant'
  content: string
  tools?: { name: string; args: any }[]
  citations?: any[]
  usage?: { prompt_tokens: number; completion_tokens: number; total_tokens: number }
}

export default function Chat() {
  const location = useLocation()
  const [agents, setAgents] = useState<any[]>([])
  const [agentId, setAgentId] = useState<number | undefined>(location.state?.agentId)
  const [conversations, setConversations] = useState<any[]>([])
  const [conversationId, setConversationId] = useState<number | null>(null)
  const [messages, setMessages] = useState<Msg[]>([])
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)
  const abortRef = useRef<AbortController | null>(null)

  const loadAgents = async () => {
    try {
      const list = (await listAgents() as any).filter((a: any) => a.status === 'published')
      setAgents(list)
      if (list.length > 0) setAgentId((prev) => prev ?? list[0].id)
    } catch {}
  }
  const loadConversations = async () => {
    try { setConversations(await listConversations() as any) } catch {}
  }
  useEffect(() => { loadAgents(); loadConversations() }, [])

  const scrollBottom = () => bottomRef.current?.scrollIntoView({ behavior: 'smooth' })

  const selectConversation = async (cid: number) => {
    setConversationId(cid)
    try {
      const msgs: any = await listMessages(cid)
      setMessages(msgs.map((m: any) => ({ role: m.role, content: m.content, tools: m.tool_calls || [], citations: m.citations || [], usage: m.token_usage || undefined })))
    } catch { message.error('加载历史失败') }
  }

  const newConversation = () => {
    setConversationId(null)
    setMessages([])
  }

  const doSend = async (msg: string, isRegen: boolean) => {
    if (!msg || !agentId || sending) return
    if (isRegen) {
      setMessages((prev) => {
        const next = [...prev]
        next.pop()
        next.push({ role: 'assistant', content: '' })
        return next
      })
    } else {
      setMessages((prev) => [...prev, { role: 'user', content: msg }, { role: 'assistant', content: '' }])
      setInput('')
    }
    setSending(true)
    const controller = new AbortController()
    abortRef.current = controller

    try {
      const token = localStorage.getItem('token')
      const res = await fetch('/api/v1/agents/' + agentId + '/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + token },
        body: JSON.stringify({ message: msg, conversation_id: conversationId }),
        signal: controller.signal,
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        throw new Error(err.detail || '请求失败')
      }
      const reader = res.body!.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      let newCid = conversationId
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const parts = buffer.split('\n\n')
        buffer = parts.pop() || ''
        for (const part of parts) {
          if (!part.startsWith('data: ')) continue
          let evt: any
          try { evt = JSON.parse(part.slice(6)) } catch { continue }
          setMessages((prev) => {
            const next = [...prev]
            const last = next[next.length - 1]
            if (evt.type === 'delta') {
              last.content += evt.content
            } else if (evt.type === 'tool_call') {
              last.tools = [...(last.tools || []), { name: evt.name, args: evt.arguments }]
            } else if (evt.type === 'error') {
              last.content += '\n[错误] ' + evt.message
            } else if (evt.type === 'done' && evt.usage) {
              last.usage = evt.usage
            }
            return next
          })
          if (evt.type === 'done' && evt.conversation_id) newCid = evt.conversation_id
        }
        scrollBottom()
      }
      if (newCid && newCid !== conversationId) {
        setConversationId(newCid)
        loadConversations()
      }
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

  return (
    <div style={{ display: 'flex', height: '100%', gap: 12, minHeight: 0 }}>
      {/* 左侧会话列表 */}
      <div style={{ width: 220, border: '1px solid #eee', borderRadius: 8, padding: 12, display: 'flex', flexDirection: 'column', flexShrink: 0 }}>
        <div style={{ marginBottom: 8 }}>
          <Select
            placeholder="选择智能体"
            style={{ width: '100%' }}
            value={agentId}
            onChange={(v) => { setAgentId(v); newConversation() }}
            options={agents.map((a: any) => ({ value: a.id, label: a.name }))}
          />
        </div>
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
                  style={{ cursor: 'pointer', background: conversationId === c.id ? '#e6f4ff' : 'transparent', padding: '6px 8px', borderRadius: 6 }}
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

      {/* 右侧对话区 */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', border: '1px solid #eee', borderRadius: 8, minWidth: 0 }}>
        <div style={{ flex: 1, overflow: 'auto', padding: 16, background: '#fafafa' }}>
          {messages.length === 0 && <Empty style={{ marginTop: 60 }} description="选择一个智能体开始对话" />}
          {messages.map((m, i) => (
            <div key={i} style={{ display: 'flex', justifyContent: m.role === 'user' ? 'flex-end' : 'flex-start', marginBottom: 12 }}>
              <div style={{ maxWidth: '75%', padding: '10px 14px', borderRadius: 8, background: m.role === 'user' ? '#1e40af' : '#fff', color: m.role === 'user' ? '#fff' : '#000', border: m.role === 'user' ? 'none' : '1px solid #eee', whiteSpace: 'pre-wrap' }}>
                {m.tools?.map((t, j) => (
                  <div key={j}><Tag color="purple" style={{ marginBottom: 4 }}>🔧 {t.name}({JSON.stringify(t.args)})</Tag></div>
                ))}
                {m.role === 'user' ? (
                  <div>{m.content}</div>
                ) : (
                  <div className="markdown-body">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>{m.content || (i === messages.length - 1 && sending ? '思考中...' : '')}</ReactMarkdown>
                  </div>
                )}
                {m.citations && m.citations.length > 0 && (
                  <div style={{ marginTop: 8, paddingTop: 8, borderTop: '1px dashed #eee' }}>
                    <div style={{ fontSize: 12, color: '#999', marginBottom: 4 }}>📚 引用来源：</div>
                    {m.citations.map((c: any, k) => (
                      <div key={k} style={{ fontSize: 12, color: '#666' }}>· {c.doc_name || '文档'}：{String(c.content).slice(0, 80)}...</div>
                    ))}
                  </div>
                )}
                {m.usage && (
                  <div style={{ marginTop: 6, fontSize: 12, color: '#999' }}>⚡ {m.usage.total_tokens} tokens（输入 {m.usage.prompt_tokens} / 输出 {m.usage.completion_tokens}）</div>
                )}
              </div>
            </div>
          ))}
          <div ref={bottomRef} />
        </div>
        <div style={{ display: 'flex', gap: 8, padding: 12, borderTop: '1px solid #eee' }}>
          <Input.TextArea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onPressEnter={(e) => { if (!e.shiftKey) { e.preventDefault(); send() } }}
            placeholder="输入消息，Enter 发送，Shift+Enter 换行"
            autoSize={{ minRows: 1, maxRows: 4 }}
          />
          {sending ? (
            <Button danger icon={<StopOutlined />} onClick={stop}>停止</Button>
          ) : (
            <Button type="primary" icon={<SendOutlined />} onClick={send}>发送</Button>
          )}
          {messages.some((m) => m.role === 'user') && !sending && (
            <Button icon={<ReloadOutlined />} onClick={regenerate}>重新生成</Button>
          )}
        </div>
      </div>
    </div>
  )
}
