import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { toast } from 'sonner'
import { ChevronDown, MessageSquare, Plus } from 'lucide-react'
import Button from '../components/ui/Button'
import {
  chatAgentStream, chatModelStream, chatWorkflowStream, deleteConversation, getConversation,
  getWorkflowParameters, listConversations, listMessages, type ChatTransport, type ConversationRow, type WorkflowVariableDecl,
} from '../api'
import { visibleNavItems } from '../constants/nav'
import { useAvailableAgents } from '../hooks/useAvailableAgents'
import { useAvailableModels } from '../hooks/useAvailableModels'
import { useAvailableWorkflows } from '../hooks/useAvailableWorkflows'
import { useQueryState } from '../hooks/useQueryState'
import { useAuth } from '../store/auth'
import ChatPanel from '../components/chat/ChatPanel'
import ConversationList from '../components/chat/ConversationList'
import AgentPicker from '../components/chat/AgentPicker'
import { Tabs, TabsList, TabsTrigger } from '../components/shadcn/tabs'
import { useChatStream } from '../components/chat/useChatStream'
import { toChatMessages } from '../components/chat/messages'
import { CHAT_MESSAGE_MAX_CHARS, FULL_CAPABILITIES, type ChatCapabilities, type Msg } from '../components/chat/types'
import { errorText } from '../utils/errors'

const PAGE = 50

// 三种对话类型共用这一页：模型（直接和模型聊，无工具无知识库）、智能体（原有的装配结果对话）、
// 工作流（一句话触发一次运行）。类型与目标对象都放在地址里，刷新与分享不丢。
type ChatKind = 'model' | 'agent' | 'workflow'
const KIND_TABS: { value: ChatKind; label: string }[] = [
  { value: 'model', label: '模型' },
  { value: 'agent', label: '智能体' },
  { value: 'workflow', label: '工作流' },
]
const KIND_LABEL: Record<ChatKind, string> = { model: '模型', agent: '智能体', workflow: '工作流' }
const QUERY_DEFAULTS: { kind?: string; target?: string; conversation?: string } = { kind: undefined, target: undefined, conversation: undefined }

// 消息该填给开始节点的哪个文本变量（后端规则）：名为 input 的文本变量优先；否则唯一的文本变量就是它；
// 文本变量一个都没有、或者有多个却不叫 input，这个工作流就没法被一句自然语言触发
function readMessageVariable(variables: WorkflowVariableDecl[]): { messageVar: string | null; blockReason: string | null } {
  const texts = variables.filter((v) => v.type === 'text')
  const named = texts.find((v) => v.name === 'input')
  if (named) return { messageVar: named.name, blockReason: null }
  if (texts.length === 1) return { messageVar: texts[0].name, blockReason: null }
  if (texts.length === 0) return { messageVar: null, blockReason: '该工作流没有可用作消息输入的文本变量，不能作为对话目标' }
  return { messageVar: null, blockReason: `开始节点有多个文本变量（${texts.map((v) => v.name).join('、')}），请把其中一个命名为 input` }
}

// 聊天页：左侧按当前对象过滤的会话列表 + 右侧对话面板（ChatPanel，与装配页调试、分享访客页共用）。
// 对话类型（kind）与目标对象（target）通过 ?kind= & ?target= 深链，会话通过 ?conversation=；
// 发送走 SSE 流式接口，三种类型的传输由页面按 kind 注入，useChatStream / ChatPanel 不感知类型。
export default function Chat() {
  const [isMobile, setIsMobile] = useState(() => typeof window !== 'undefined' && window.innerWidth < 768)
  const [query, setQuery] = useQueryState(QUERY_DEFAULTS)
  const conversationId = query.conversation ? Number(query.conversation) : null
  const role = useAuth((s) => s.user?.role)
  const canManageAgents = visibleNavItems(role).some((item) => item.key === '/agents')
  // 模型 / 工作流是搭建者的能力，菜单里没有 /models 的角色（caller）只保留智能体一种对话；
  // 只有一种类型时不渲染分段控件（一个选项的分段没有意义）
  const canViewAllKinds = visibleNavItems(role).some((item) => item.key === '/models')
  const allowedKinds = useMemo<ChatKind[]>(() => (canViewAllKinds ? KIND_TABS.map((t) => t.value) : ['agent']), [canViewAllKinds])
  // 地址里的 kind 只认当前角色能看到的，其余一律落到默认类型（深链带上别人给的 kind 时不至于打开一个空页）
  const kindParam = query.kind as ChatKind | undefined
  const kind: ChatKind | undefined = kindParam && allowedKinds.includes(kindParam) ? kindParam : undefined
  // 没写 kind 时默认智能体：这一页原本就是智能体对话，外部入口（智能体详情的"对话"）也只传 target
  const defaultKind: ChatKind = allowedKinds.includes('agent') ? 'agent' : allowedKinds[0]
  const targetId = query.target ? Number(query.target) : undefined

  const { agents, loaded: agentsLoaded, remote: remoteSearch, onSearch } = useAvailableAgents(kind === 'agent' ? targetId : undefined)
  // caller 只有智能体一种对话，模型 / 工作流列表不必请求（否则会拿到 403 再弹错误提示）
  const { items: models, loaded: modelsLoaded } = useAvailableModels(canViewAllKinds)
  const { items: workflows, loaded: workflowsLoaded } = useAvailableWorkflows(canViewAllKinds)

  // docs/15 D-19：admin / developer 全部可见；调用者不看运行记录链接（无权访问）与工具入参和结果（可能含内部地址）
  const canViewRuns = visibleNavItems(role).some((item) => item.key === '/runs')
  const capabilities = useMemo<ChatCapabilities>(() => (canViewRuns ? FULL_CAPABILITIES : { ...FULL_CAPABILITIES, showRunLink: false, showToolDetails: false }), [canViewRuns])
  const [conversations, setConversations] = useState<ConversationRow[]>([])
  const [total, setTotal] = useState(0)
  const [q, setQ] = useState<string | undefined>()
  const [messages, setMessages] = useState<Msg[]>([])
  const [loadingMessages, setLoadingMessages] = useState(false)
  const [showList, setShowList] = useState(false)
  // 工作流对话的输入声明：null 表示还没读到（读取中也算），读失败时置 error 并按"不能对话"处理
  const [workflowVars, setWorkflowVars] = useState<WorkflowVariableDecl[] | null>(null)
  const [workflowVarsFailed, setWorkflowVarsFailed] = useState(false)
  // 地址补全只做一次：否则 target_id 为空的老会话会反复触发同一请求
  const autoFilled = useRef<string | null>(null)

  // 断点用 matchMedia 判断，不再依赖 antd Grid 的 JS 断点
  useEffect(() => {
    const mq = window.matchMedia('(max-width: 767px)')
    const onChange = () => setIsMobile(mq.matches)
    onChange()
    mq.addEventListener('change', onChange)
    return () => mq.removeEventListener('change', onChange)
  }, [])

  // 地址补全：深链可能只带会话（智能体会话页签、运行详情的"查看会话"），也可能什么都没带。
  // 带了会话就以会话自己的归属为准补齐 kind / target —— 拿第一个对象顶替会让续聊落到别人的会话上（后端 404）。
  useEffect(() => {
    if (kind && targetId) return
    const key = conversationId ? `c:${conversationId}` : 'fresh'
    if (autoFilled.current === key) return
    autoFilled.current = key
    if (!conversationId) {
      // 地址里可能只有 target（智能体详情的"对话"入口）：补上类型即可
      if (!kind) setQuery({ kind: defaultKind })
      return
    }
    let cancelled = false
    getConversation(conversationId)
      .then((conv) => {
        if (cancelled) return
        // 会话类型不在本角色可见范围时退回默认类型，至少让页面能用
        const convKind: ChatKind = allowedKinds.includes(conv.kind) ? conv.kind : defaultKind
        setQuery({ kind: convKind, target: conv.target_id ? String(conv.target_id) : undefined })
      })
      .catch((e) => {
        if (cancelled) return
        toast.error(errorText(e, '会话不存在或已删除'))
        setQuery({ conversation: undefined })
      })
    return () => { cancelled = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [kind, targetId, conversationId])

  const pickerOptions = useMemo(() => (
    kind === 'model' ? models.map((m) => ({ value: m.id, label: m.name }))
      : kind === 'workflow' ? workflows.map((w) => ({ value: w.id, label: w.name }))
        : agents.map((a) => ({ value: a.id, label: a.name }))
  ), [kind, models, workflows, agents])
  const pickerLoaded = kind === 'model' ? modelsLoaded : kind === 'workflow' ? workflowsLoaded : agentsLoaded

  // 只带 kind 不带 target 时落到该类型的第一个选项；带会话时不抢，归属交给上面那步决定
  useEffect(() => {
    if (!kind || targetId || !pickerLoaded || conversationId) return
    const first = pickerOptions[0]
    if (first) setQuery({ target: String(first.value) })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [kind, targetId, pickerLoaded, conversationId])

  // 工作流对话要先知道消息填给哪个变量：选中工作流后读一次输入声明；读不到就让页面按"不能对话"降级，不能崩
  useEffect(() => {
    setWorkflowVars(null)
    setWorkflowVarsFailed(false)
    if (kind !== 'workflow' || !targetId) return
    let cancelled = false
    getWorkflowParameters(targetId)
      .then((p) => { if (!cancelled) setWorkflowVars(p.variables) })
      .catch((e) => {
        if (cancelled) return
        setWorkflowVarsFailed(true)
        toast.error(errorText(e, '读取工作流输入声明失败'))
      })
    return () => { cancelled = true }
  }, [kind, targetId])

  const loadConversations = useCallback(async (page = 1) => {
    if (!kind || !targetId) return
    try {
      const res = await listConversations({ kind, target_id: targetId, q, page, page_size: PAGE })
      setConversations((prev) => (page === 1 ? res.items : [...prev, ...res.items]))
      setTotal(res.total)
    } catch (e) { toast.error(errorText(e, '加载会话失败')) }
  }, [kind, targetId, q])
  useEffect(() => { loadConversations(1) }, [loadConversations])

  // 切换会话：拉取历史并归一化成对话面板的消息结构；切走时先清空避免露出旧内容
  useEffect(() => {
    if (!conversationId) { setMessages([]); return }
    let cancelled = false
    setMessages([])
    setLoadingMessages(true)
    listMessages(conversationId)
      .then((rows) => { if (!cancelled) setMessages(toChatMessages(rows)) })
      .catch((e) => { if (!cancelled) toast.error(errorText(e, '加载历史失败')) })
      .finally(() => { if (!cancelled) setLoadingMessages(false) })
    return () => { cancelled = true }
  }, [conversationId])

  // 工作流能不能对话：参数还没读到、读失败、没有合适的文本变量，都视为不能发
  const workflowChoice = workflowVars ? readMessageVariable(workflowVars) : null
  const workflowBlocked = kind === 'workflow' && !workflowChoice?.messageVar

  const transport = useMemo<ChatTransport | undefined>(() => {
    if (!targetId || workflowBlocked) return undefined
    if (kind === 'model') return (payload, handlers, signal) => chatModelStream(targetId, payload, handlers, signal)
    if (kind === 'workflow') return (payload, handlers, signal) => chatWorkflowStream(targetId, payload, handlers, signal)
    return (payload, handlers, signal) => chatAgentStream(targetId, payload, handlers, signal)
  }, [kind, targetId, workflowBlocked])
  const stream = useChatStream(messages, setMessages, {
    transport, conversationId,
    onConversationCreated: (id) => { setQuery({ conversation: String(id) }); loadConversations(1) },
  })

  const kindLabel = KIND_LABEL[kind ?? 'agent']
  const currentName = pickerOptions.find((o) => o.value === targetId)?.label
  // 头部副标题只对智能体 / 工作流有意义（模型没有简介字段）
  const currentDescription = kind === 'model' ? null
    : kind === 'workflow' ? workflows.find((w) => w.id === targetId)?.description ?? null
      : agents.find((a) => a.id === targetId)?.description ?? null

  // 输入框上方的一行说明：不可对话时讲清原因（并禁用输入），可对话时说明消息会落到哪个变量
  let workflowHint: { text: string; tone: 'muted' | 'danger' } | null = null
  if (kind === 'workflow') {
    if (workflowVarsFailed) workflowHint = { text: '读取该工作流的输入声明失败，暂时不能作为对话目标', tone: 'danger' }
    else if (!workflowVars) workflowHint = targetId ? { text: '正在读取工作流的输入声明…', tone: 'muted' } : null
    else if (workflowChoice?.messageVar) workflowHint = { text: `消息将填入变量 ${workflowChoice.messageVar}`, tone: 'muted' }
    else workflowHint = { text: workflowChoice?.blockReason ?? '该工作流不能作为对话目标', tone: 'danger' }
  }

  const emptyPickerText = kind === 'model' ? '还没有启用的模型，先去模型页添加并启用一个'
    : kind === 'workflow' ? '还没有工作流，先去工作流页创建一个'
      : canManageAgents ? '没有已发布的智能体，先去智能体页发布一个' : '还没有可用的智能体，请联系管理员发布'
  const emptyChatText = currentName ? `向「${currentName}」发送第一条消息开始对话` : `先在左侧选择一个${kindLabel}`

  const pickerPlaceholder = kind === 'model' ? '选择模型' : kind === 'workflow' ? '选择工作流' : '选择已发布的智能体'

  // 换对话类型等于换一整套对象：会话与消息都属于上一个对象，留着只会串味；target 清空后由上面的 effect 落到第一个选项
  const switchKind = (next: ChatKind) => {
    if (next === kind) return
    autoFilled.current = null // 清掉"补过一次"的标记，新类型还没补 target，要重新走一次补全
    setMessages([])
    setShowList(false)
    setQuery({ kind: next, target: undefined, conversation: undefined })
  }

  const agentSelector = (
    <>
      {allowedKinds.length > 1 && kind && (
        // 分段控件放在会话侧栏顶部而不是对话头部：头部在窄屏只剩名称与两个按钮的位置，塞三个标签会把标题挤没
        <Tabs value={kind} onValueChange={(v) => switchKind(v as ChatKind)}>
          <TabsList className="h-7 w-full">
            {KIND_TABS.filter((t) => allowedKinds.includes(t.value)).map((t) => (
              <TabsTrigger key={t.value} value={t.value} className="text-[12px]">{t.label}</TabsTrigger>
            ))}
          </TabsList>
        </Tabs>
      )}
      <AgentPicker
        value={targetId ?? null}
        options={pickerOptions}
        remoteSearch={kind === 'agent' && remoteSearch}
        onSearch={kind === 'agent' ? onSearch : undefined}
        emptyText={emptyPickerText}
        placeholder={pickerPlaceholder}
        onChange={(v) => { setQuery({ target: String(v), conversation: undefined }); setMessages([]) }}
      />
    </>
  )

  const newConversation = () => { setQuery({ conversation: undefined }); setMessages([]); setShowList(false) }
  const removeConversation = async (id: number) => {
    await deleteConversation(id)
    if (conversationId === id) newConversation()
    loadConversations(1)
  }

  const sidebar = (
    <div className="h-full min-h-0 shrink-0 rounded-xl border border-border bg-card p-3" style={{ width: isMobile ? '100%' : 240 }}>
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
      {isMobile && (
        <Button size="sm" variant="secondary" icon={<MessageSquare />} onClick={() => setShowList(true)}>会话</Button>
      )}
      <div className="min-w-0 flex-1">
        <div className="truncate text-[14px] font-semibold text-foreground">{currentName ?? `未选择${kindLabel}`}</div>
        {currentDescription && (
          <div className="truncate text-[12px] text-muted-foreground">{currentDescription}</div>
        )}
      </div>
      {isMobile && (
        <Button size="sm" variant="secondary" icon={<Plus />} onClick={newConversation} aria-label="新建会话" />
      )}
    </>
  )
  // 说明行放在面板外侧的顶部：ChatPanel 的 props 形状三处共用，不为一个提示去改它的接口
  const hintLine = workflowHint && (
    <div
      className="shrink-0 rounded-lg px-3 py-1.5 text-[12.5px] leading-relaxed"
      style={workflowHint.tone === 'danger'
        ? { background: 'var(--danger-soft)', color: 'var(--danger)' }
        : { background: 'var(--bg-soft-2)', color: 'var(--fg-muted)' }}
    >
      {workflowHint.text}
    </div>
  )
  const inputPlaceholder = !targetId ? `先选择一个${kindLabel}`
    : workflowBlocked ? (workflowHint?.text ?? '该工作流暂不能作为对话目标')
      : kind === 'workflow' && workflowChoice?.messageVar ? `输入消息，将填入变量 ${workflowChoice.messageVar}，Enter 发送`
        : undefined
  const chatArea = (
    <div className="flex min-h-0 min-w-0 flex-1 flex-col gap-2">
      {hintLine}
      <ChatPanel
        header={header} messages={messages} sending={stream.sending} loading={loadingMessages} isMobile={isMobile}
        emptyHint={emptyChatText}
        inputDisabled={!targetId || workflowBlocked} maxLength={CHAT_MESSAGE_MAX_CHARS} capabilities={capabilities}
        agentName={currentName}
        inputPlaceholder={inputPlaceholder}
        onSend={stream.send} onStop={stream.stop} onRegenerate={stream.regenerate}
      />
    </div>
  )

  if (isMobile) return <div className="flex min-h-0 flex-1 flex-col">{showList ? sidebar : chatArea}</div>
  return <div className="flex min-h-0 flex-1 gap-3">{sidebar}{chatArea}</div>
}
