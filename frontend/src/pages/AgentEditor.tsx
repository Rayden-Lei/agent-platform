import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { toast } from 'sonner'
import { PanelRight } from 'lucide-react'
import { useNavigate, useParams } from 'react-router-dom'
import { deleteAgent, getAgent, listKBs, listModels, listPromptTemplates, listTools, offlineAgent, publishAgent, renderPromptTemplate, updateAgent, OPTIONS_PAGE } from '../api'
import { useAsyncData } from '../hooks/useAsyncData'
import { useAvailableSkills } from '../hooks/useAvailableSkills'
import { useAgentDebug } from '../hooks/useAgentDebug'
import { useGuardedNavigate } from '../hooks/useGuardedNavigate'
import { useUnsaved } from '../store/unsaved'
import { Skeleton } from '@/components/shadcn/skeleton'
import ErrorState from '../components/common/ErrorState'
import EditorHeader from '../components/agents/editor/EditorHeader'
import ConfigSections, { EDITOR_SECTIONS, sectionId, toFormValues, toPayload, validateAgentConfig, type AgentConfigValues } from '../components/agents/editor/ConfigSections'
import PublishModal from '../components/agents/PublishModal'
import DebugPanel from '../components/agents/debug/DebugPanel'
import Modal from '../components/ui/Modal'
import Button from '../components/ui/Button'
import { errorText } from '../utils/errors'

// 智能体装配页 /agents/:id/edit（docs/15 3.3、3.4，FR-040 / FR-041）：顶栏钉死，左侧锚点 + 分区配置、右栏当场调试，各自滚动，整页不滚。
// 保存只改草稿（发布后才对外生效）；带读到的 updated_at 保存，期间被别人改过 409。未保存判断 = 请求体与上次保存时不同。
// 编辑态由本页持有（values + onChange），ConfigSections 只渲染与回传补丁。
export default function AgentEditor() {
  const agentId = Number(useParams().id)
  const navigate = useNavigate()
  const guardedNavigate = useGuardedNavigate()
  const dirty = useUnsaved((s) => s.dirty)
  const setDirty = useUnsaved((s) => s.setDirty)
  const [compact, setCompact] = useState(() => typeof window !== 'undefined' && window.innerWidth < 1024)
  const [values, setValues] = useState<AgentConfigValues | null>(null)
  const baseline = useRef('')
  const scrollRef = useRef<HTMLDivElement>(null)
  const [saving, setSaving] = useState(false)
  const [publishOpen, setPublishOpen] = useState(false)
  const [debugOpen, setDebugOpen] = useState(true) // 桌面端右栏调试区可收起
  const [pane, setPane] = useState<'config' | 'debug'>('config') // 移动端两个页签
  const [confirm, setConfirm] = useState<'offline' | 'delete' | null>(null)

  // 调试对象 = 编辑器当前内容（含未保存修改），每轮发送时现取
  const getConfig = useCallback(() => toPayload((values ?? {}) as Record<string, unknown>), [values])
  const debug = useAgentDebug(agentId, getConfig)
  const detail = useAsyncData(() => getAgent(agentId), [agentId], { errorText: '加载智能体失败' })
  const options = useAsyncData(() => Promise.all([listModels(OPTIONS_PAGE), listKBs(OPTIONS_PAGE), listTools(OPTIONS_PAGE), listPromptTemplates(OPTIONS_PAGE)]), [], { errorText: '加载下拉选项失败' })
  const agent = detail.data
  const [models, kbs, tools, templates] = options.data ?? []
  // 技能只列启用的；已绑定的停用技能由 mergeSkillOptions 补回来，否则触发器只显示一个数字
  const { items: skills } = useAvailableSkills()

  useEffect(() => {
    const onResize = () => setCompact(window.innerWidth < 1024)
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [])

  // 草稿内容变了（首次加载、保存后刷新）才回填并重置基线；发布、下线只改状态，不能冲掉正在编辑的未保存内容
  const filledDraft = useRef('')
  useEffect(() => {
    if (!agent) return
    const draft = JSON.stringify(agent.draft_snapshot)
    if (draft === filledDraft.current) return
    filledDraft.current = draft
    const next = toFormValues(agent)
    setValues(next)
    baseline.current = JSON.stringify(toPayload(next as unknown as Record<string, unknown>))
    setDirty(false)
  }, [agent, setDirty])
  useEffect(() => () => setDirty(false), [setDirty])

  const onChange = useCallback((patch: Partial<AgentConfigValues>) => {
    setValues((prev) => {
      if (!prev) return prev
      const next = { ...prev, ...patch }
      setDirty(JSON.stringify(toPayload(next as unknown as Record<string, unknown>)) !== baseline.current)
      return next
    })
  }, [setDirty])

  const errors = useMemo(() => (values ? validateAgentConfig(values) : {}), [values])

  const names = useMemo(() => ({
    model: Object.fromEntries((models?.items ?? []).map((m) => [m.id, m.name])),
    kb: Object.fromEntries((kbs?.items ?? []).map((k) => [k.id, k.name])),
    tool: Object.fromEntries((tools?.items ?? []).map((t) => [t.id, t.name])),
    // 快照里只存 skill_ids，名称取详情附带的已绑定技能（显示名比 name 好认）
    skill: Object.fromEntries((agent?.skills ?? []).map((s) => [s.id, s.display_name])),
  }), [models, kbs, tools, agent])

  const onSave = async () => {
    if (!agent?.updated_at || !values) return
    // 分区里的错误提示是"碰过才显示"，保存时统一拦一次
    const first = Object.values(errors).find(Boolean)
    if (first) { toast.error(first); return }
    setSaving(true)
    try {
      const payload = toPayload(values as unknown as Record<string, unknown>)
      const saved = await updateAgent(agentId, { ...payload, expected_updated_at: agent.updated_at })
      // 保存的内容就是新基线；服务端若改写了内容（按模板重新渲染等），刷新后草稿快照变化会再回填一次
      baseline.current = JSON.stringify(payload)
      setDirty(false)
      toast.success(saved.published_version ? '已保存草稿，发布后对外生效' : '已保存草稿')
      await detail.reload(true)
    } catch (e) {
      toast.error(errorText(e, '保存失败'))
    } finally {
      setSaving(false)
    }
  }

  const onPublish = async (note?: string) => {
    try {
      const r = await publishAgent(agentId, note)
      toast.success(r.publish_result === 'unchanged' ? '草稿与线上一致，无需发布' : `已发布，线上为 v${r.published_version}`)
      setPublishOpen(false)
      await detail.reload(true)
    } catch (e) {
      toast.error(errorText(e, '发布失败'))
      throw e
    }
  }

  const doOffline = async () => {
    try {
      await offlineAgent(agentId)
      toast.success('已下线')
      setConfirm(null)
      await detail.reload(true)
    } catch (e) { toast.error(errorText(e, '下线失败')) }
  }
  const doDelete = async () => {
    try {
      await deleteAgent(agentId)
      setDirty(false)
      setConfirm(null)
      toast.success('已删除')
      navigate('/agents')
    } catch (e) { toast.error(errorText(e, '删除失败')) }
  }

  const jumpTo = (key: string) => {
    const el = document.getElementById(sectionId(key))
    el?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  if (detail.error) {
    return (
      <div className="flex min-h-0 flex-1 flex-col overflow-auto">
        <ErrorState message={detail.error} onRetry={() => detail.reload()} />
        <div className="text-center"><Button variant="secondary" size="md" onClick={() => navigate('/agents')}>返回智能体列表</Button></div>
      </div>
    )
  }
  if (!agent || !values) {
    return (
      <div className="flex flex-col gap-3">
        <Skeleton className="h-12 w-full" />
        <Skeleton className="h-40 w-full" />
        <Skeleton className="h-40 w-full" />
      </div>
    )
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3">
      <EditorHeader
        agent={agent}
        dirty={dirty}
        saving={saving}
        compact={compact}
        onBack={() => guardedNavigate(`/agents/${agentId}`)}
        onSave={onSave}
        onPublish={() => setPublishOpen(true)}
        onOpenDetail={() => guardedNavigate(`/agents/${agentId}`)}
        onOffline={() => setConfirm('offline')}
        onDelete={() => setConfirm('delete')}
      />
      {options.error && <ErrorState compact message={options.error} onRetry={() => options.reload()} />}

      {compact && (
        <div className="flex shrink-0 rounded-lg border border-border p-0.5">
          {([['config', '配置'], ['debug', '调试']] as const).map(([key, label]) => (
            <button
              key={key}
              type="button"
              onClick={() => setPane(key)}
              className={`h-7 flex-1 rounded-md text-[13px] transition-colors ${pane === key ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:bg-accent'}`}
            >
              {label}
            </button>
          ))}
        </div>
      )}

      <div className="flex min-h-0 flex-1 gap-3">
        {!compact && (
          <nav className="w-[132px] shrink-0" aria-label="分区导航">
            <ul className="m-0 flex list-none flex-col gap-0.5 p-0">
              {EDITOR_SECTIONS.map((s) => (
                <li key={s.key}>
                  <button
                    type="button"
                    onClick={() => jumpTo(s.key)}
                    className="w-full rounded-md px-2.5 py-1.5 text-left text-[12.5px] text-muted-foreground hover:bg-accent hover:text-foreground"
                  >
                    {s.title}
                  </button>
                </li>
              ))}
            </ul>
          </nav>
        )}
        {/* 移动端切到"调试"时配置区只隐藏不卸载：调试取的是当前 values */}
        <div
          ref={scrollRef}
          className="min-w-0 flex-1 overflow-auto"
          style={{ display: compact && pane === 'debug' ? 'none' : undefined }}
        >
          <ConfigSections
            values={values}
            onChange={onChange}
            models={models?.items ?? []}
            templates={templates?.items ?? []}
            kbOptions={mergeOptions(kbs?.items ?? [], agent?.knowledge_bases ?? [])}
            toolOptions={(tools?.items ?? []).map((t) => ({
              value: t.id,
              // MCP 工具要标出来源服务器：名字是 {server}_{remote} 拼的，光看名字认不出来
              label: (t.is_enabled ? t.name : `${t.name}（已停用）`) + (t.type === 'mcp' && t.mcp_server_name ? ` · MCP ${t.mcp_server_name}` : ''),
            }))}
            skillOptions={mergeSkillOptions(skills, agent?.skills ?? [])}
            onRenderTemplate={renderPromptTemplate}
          />
        </div>

        {(compact ? pane === 'debug' : debugOpen) ? (
          <div className="flex min-h-0 min-w-0" style={{ width: compact ? undefined : 440, flex: compact ? 1 : undefined, flexShrink: 0 }}>
            <DebugPanel
              messages={debug.messages}
              sending={debug.sending}
              compact={compact}
              onSend={debug.send}
              onStop={debug.stop}
              onRegenerate={debug.regenerate}
              onClear={debug.clear}
              onCollapse={compact ? undefined : () => setDebugOpen(false)}
            />
          </div>
        ) : !compact ? (
          <Button variant="secondary" size="sm" className="shrink-0" icon={<PanelRight />} onClick={() => setDebugOpen(true)}>调试</Button>
        ) : null}
      </div>

      <PublishModal agent={publishOpen ? agent : null} names={names} onClose={() => setPublishOpen(false)} onPublish={onPublish} />

      <Modal
        open={confirm === 'offline'}
        size="sm"
        title="下线这个智能体？"
        description="对话、API Key 与工作流都不能再调用它；线上版本保留，重新发布即恢复。"
        onClose={() => setConfirm(null)}
        footer={<><Button variant="ghost" size="md" onClick={() => setConfirm(null)}>取消</Button><Button variant="danger" size="md" onClick={doOffline}>下线</Button></>}
      >
        <p className="m-0 text-[13px] text-muted-foreground">下线后重新发布即可恢复，已产生的会话与运行记录不受影响。</p>
      </Modal>

      <Modal
        open={confirm === 'delete'}
        size="sm"
        title="删除这个智能体？"
        description="会话、消息与运行记录会一并删除，不可恢复。"
        onClose={() => setConfirm(null)}
        footer={<><Button variant="ghost" size="md" onClick={() => setConfirm(null)}>取消</Button><Button variant="danger" size="md" onClick={doDelete}>删除</Button></>}
      >
        <p className="m-0 text-[13px] text-muted-foreground">删除不可恢复。如果只是想停止对外服务，建议用「下线」。</p>
      </Modal>
    </div>
  )
}

// 知识库下拉 = 当前角色可见的前 100 个 + 本智能体已绑定的（详情里带名称）：管理员绑上的受限库对开发者不在列表里（docs/15 KB-01），
// 超过 100 个时靠后的也不在，不补上就只显示一个数字
function mergeOptions(listed: { id: number; name: string }[], bound: { id: number; name: string }[]) {
  const seen = new Set(listed.map((k) => k.id))
  return [...listed, ...bound.filter((k) => !seen.has(k.id))].map((k) => ({ value: k.id, label: k.name }))
}

// 技能下拉 = 启用中的前 100 个 + 本智能体已绑定的（详情里带名称）：停用的技能不在下拉列表里，
// 绑过的要能看见并解绑。常驻的要标出来 —— 它每轮都占上下文，选之前得知道。
function mergeSkillOptions(
  listed: { id: number; display_name: string; always_on: boolean }[],
  bound: { id: number; display_name: string; always_on: boolean; is_enabled: boolean }[],
) {
  const seen = new Set(listed.map((s) => s.id))
  return [
    ...listed.map((s) => ({ value: s.id, label: skillLabel(s.display_name, s.always_on, true) })),
    ...bound.filter((s) => !seen.has(s.id)).map((s) => ({ value: s.id, label: skillLabel(s.display_name, s.always_on, s.is_enabled) })),
  ]
}

const skillLabel = (displayName: string, alwaysOn: boolean, isEnabled: boolean) =>
  `${displayName}${alwaysOn ? '（常驻）' : ''}${isEnabled ? '' : '（已停用）'}`
