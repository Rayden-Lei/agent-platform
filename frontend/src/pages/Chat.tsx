import { useEffect, useRef, useState } from 'react'
import { Select, Input, Button, message, List, Empty, Popconfirm, Grid } from 'antd'
import { SendOutlined, PlusOutlined, DeleteOutlined, StopOutlined, ReloadOutlined, MessageOutlined } from '@ant-design/icons'
import { useLocation } from 'react-router-dom'
import { listAgents, listConversations, listMessages, deleteConversation, chatAgentStream, OPTIONS_PAGE } from '../api'
import AssistantMessage from '../components/chat/AssistantMessage'
import type { Msg, ToolStep } from '../components/chat/types'

const { useBreakpoint } = Grid

// 聊天页：左侧会话列表 + 右侧消息流。发送走 SSE 流式接口（chatAgentStream）：
// 流式期间把增量文本/工具调用/引用逐段 patch 到"最后一条 assistant 消息"上；
// 支持停止生成（AbortController 中断 fetch）、重新生成、切换智能体时新建会话。
export default function Chat() {
  const location = useLocation()
  const screens = useBreakpoint()
  const isMobile = !screens.md
  const [agents, setAgents] = useState<any[]>([])
  // 当前智能体：优先取路由 state 带过来的 agentId（从 Agents 页"对话"跳入），否则默认第一个
  const [agentId, setAgentId] = useState<number | undefined>(location.state?.agentId)
  const [conversations, setConversations] = useState<any[]>([])
  // conversationId 为 null 表示"新会话"：尚未落库，等首条消息流结束后由 done 事件带回新 id
  const [conversationId, setConversationId] = useState<number | null>(null)
  const [messages, setMessages] = useState<Msg[]>([])
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  // 移动端：会话列表与聊天区二选一显示（showList 控制）
  const [showList, setShowList] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)
  // 当前流式请求的 AbortController："停止"按钮通过它中断整个 SSE 流
  const abortRef = useRef<AbortController | null>(null)

  const loadAgents = async () => {
    try {
      // 只展示已发布（published）的智能体，草稿不可对话
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

  // 切换会话：拉取历史消息，并把服务端结构归一化成前端 Msg/ToolStep 结构
  // （tool_calls → tools、token_usage → usage；历史消息的工具步骤视为已结束）
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

  // 新建会话：只清空本地状态，不发接口；真正的落库发生在首条消息流结束时
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

  // 核心发送逻辑：msg 为本次输入，isRegen 表示"重新生成"（基于上一条用户消息重发）。
  // 流程：先落一条空的 assistant 占位消息 → 建 AbortController → 调 SSE 流式接口，
  // 流式事件通过 patchLast 逐段更新最后一条 assistant 消息 → 结束后同步会话 id。
  const doSend = async (msg: string, isRegen: boolean) => {
    if (!msg || !agentId || sending) return
    if (isRegen) {
      // 重新生成：弹掉最后一条 assistant（上次的回答），再补一条新的空占位
      setMessages((prev) => { const next = [...prev]; next.pop(); next.push({ role: 'assistant', content: '' }); return next })
    } else {
      // 普通发送：追加一条 user 消息 + 一条空的 assistant 占位（流式内容将写入它）
      setMessages((prev) => [...prev, { role: 'user', content: msg }, { role: 'assistant', content: '' }])
      setInput('')
    }
    setSending(true)
    // 记住本次请求的 AbortController，"停止"按钮中断它；流结束后置空
    const controller = new AbortController()
    abortRef.current = controller

    try {
      const newCid = await chatAgentStream(agentId, { message: msg, conversation_id: conversationId }, {
        onCitations: (citations) => patchLast((last) => { last.citations = citations }),
        // 增量文本：每次 delta 拼接到最后一条 assistant 消息，实现打字机式流式输出
        onDelta: (content) => patchLast((last) => { last.content += content }),
        // 工具调用开始：往消息的 tools 里追加一条 running 状态的步骤
        onToolCall: (tc) => patchLast((last) => {
          last.tools = [...(last.tools || []), { id: tc.id, name: tc.name || '工具', args: tc.arguments ?? {}, status: 'running' as const }]
        }),
        // 工具结果返回：优先按 tool_call_id 精确匹配，匹配不到回退到第一条仍 running 的步骤
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
        // 服务端流内错误：以文本形式拼进消息内容，与正常输出同屏展示
        onError: (errMsg) => patchLast((last) => { last.content += '\n[错误] ' + errMsg }),
        // 流结束：附带 token 用量；首条消息时服务端会回传新建会话的 id
        onDone: (evt) => patchLast((last) => { if (evt.usage) last.usage = evt.usage }),
      }, controller.signal)
      // 首条消息后 conversation_id 从 null 变为真实值：记录新会话并刷新会话列表
      if (newCid && newCid !== conversationId) { setConversationId(newCid); loadConversations() }
    } catch (e: any) {
      // 主动停止产生 AbortError，属预期行为，静默返回不提示错误
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
  // 停止生成：中断当前 SSE 流（fetch 抛 AbortError，doSend 的 catch 里静默处理）
  const stop = () => { abortRef.current?.abort() }
  // 重新生成：找到最后一条 user 消息，以它重发（isRegen=true 会先弹掉上次的回答）
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
          // 只有"最后一条且正在发送中的 assistant 消息"才算流式中，驱动打字光标/加载态
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
          // 流式进行中：发送按钮切换为"停止"
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
