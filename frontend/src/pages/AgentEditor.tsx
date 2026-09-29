import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Anchor, Button, Form, Grid, Modal, Segmented, Skeleton, message } from 'antd'
import { MenuFoldOutlined } from '@ant-design/icons'
import { useNavigate, useParams } from 'react-router-dom'
import { deleteAgent, getAgent, listKBs, listModels, listPromptTemplates, listTools, offlineAgent, publishAgent, renderPromptTemplate, updateAgent, OPTIONS_PAGE } from '../api'
import { useAsyncData } from '../hooks/useAsyncData'
import { useAgentDebug } from '../hooks/useAgentDebug'
import { useGuardedNavigate } from '../hooks/useGuardedNavigate'
import { useUnsaved } from '../store/unsaved'
import ErrorState from '../components/common/ErrorState'
import EditorHeader from '../components/agents/editor/EditorHeader'
import ConfigSections, { EDITOR_SECTIONS, sectionId, toFormValues, toPayload } from '../components/agents/editor/ConfigSections'
import PublishModal from '../components/agents/PublishModal'
import DebugPanel from '../components/agents/debug/DebugPanel'
import { errorText } from '../utils/errors'

// 智能体装配页 /agents/:id/edit（docs/15 3.3、3.4，FR-040 / FR-041）：顶栏钉死，左侧锚点 + 分区配置、右栏当场调试，各自滚动，整页不滚。
// 保存只改草稿（发布后才对外生效）；带读到的 updated_at 保存，期间被别人改过 409。未保存判断 = 保存请求体与上次保存时不同。
export default function AgentEditor() {
  const agentId = Number(useParams().id)
  const navigate = useNavigate()
  const guardedNavigate = useGuardedNavigate()
  const dirty = useUnsaved((s) => s.dirty)
  const setDirty = useUnsaved((s) => s.setDirty)
  const compact = !Grid.useBreakpoint().md
  const [form] = Form.useForm()
  const baseline = useRef('')
  const scrollRef = useRef<HTMLDivElement>(null)
  const [saving, setSaving] = useState(false)
  const [publishOpen, setPublishOpen] = useState(false)
  const [debugOpen, setDebugOpen] = useState(true) // 桌面端右栏调试区可收起
  const [pane, setPane] = useState<'config' | 'debug'>('config') // 移动端两个页签
  // 调试对象 = 编辑器当前内容（含未保存修改），每轮发送时现取
  const getConfig = useCallback(() => toPayload(form.getFieldsValue(true)), [form])
  const debug = useAgentDebug(agentId, getConfig)
  const detail = useAsyncData(() => getAgent(agentId), [agentId], { errorText: '加载智能体失败' })
  const options = useAsyncData(() => Promise.all([listModels(OPTIONS_PAGE), listKBs(OPTIONS_PAGE), listTools(OPTIONS_PAGE), listPromptTemplates(OPTIONS_PAGE)]), [], { errorText: '加载下拉选项失败' })
  const agent = detail.data
  const [models, kbs, tools, templates] = options.data ?? []

  // 草稿内容变了（首次加载、保存后刷新）才回填并重置基线；发布、下线只改状态，不能冲掉正在编辑的未保存内容
  const filledDraft = useRef('')
  useEffect(() => {
    if (!agent) return
    const draft = JSON.stringify(agent.draft_snapshot)
    if (draft === filledDraft.current) return
    filledDraft.current = draft
    form.resetFields()
    form.setFieldsValue(toFormValues(agent))
    baseline.current = JSON.stringify(toPayload(form.getFieldsValue(true)))
    setDirty(false)
  }, [agent, form, setDirty])
  useEffect(() => () => setDirty(false), [setDirty])
  const onValuesChange = useCallback(() => setDirty(JSON.stringify(toPayload(form.getFieldsValue(true))) !== baseline.current), [form, setDirty])

  const names = useMemo(() => ({
    model: Object.fromEntries((models?.items ?? []).map((m) => [m.id, m.name])),
    kb: Object.fromEntries((kbs?.items ?? []).map((k) => [k.id, k.name])),
    tool: Object.fromEntries((tools?.items ?? []).map((t) => [t.id, t.name])),
  }), [models, kbs, tools])

  const onSave = async (values: Record<string, unknown>) => {
    if (!agent?.updated_at) return
    setSaving(true)
    try {
      const saved = await updateAgent(agentId, { ...toPayload(values), expected_updated_at: agent.updated_at })
      // 保存的内容就是新基线；服务端若改写了内容（按模板重新渲染等），刷新后草稿快照变化会再回填一次
      baseline.current = JSON.stringify(toPayload(values))
      setDirty(false)
      message.success(saved.published_version ? '已保存草稿，发布后对外生效' : '已保存草稿')
      await detail.reload(true)
    } catch (e) { message.error(errorText(e, '保存失败')) } finally { setSaving(false) }
  }
  const onPublish = async (note?: string) => {
    try {
      const r = await publishAgent(agentId, note)
      message.success(r.publish_result === 'unchanged' ? '草稿与线上一致，无需发布' : `已发布，线上为 v${r.published_version}`)
      setPublishOpen(false)
      await detail.reload(true)
    } catch (e) { message.error(errorText(e, '发布失败')); throw e }
  }
  const onOffline = () => Modal.confirm({
    title: '下线这个智能体？', content: '对话、API Key 与工作流都不能再调用它；线上版本保留，重新发布即恢复。', okText: '下线', okButtonProps: { danger: true },
    onOk: async () => { try { await offlineAgent(agentId); message.success('已下线'); await detail.reload(true) } catch (e) { message.error(errorText(e, '下线失败')) } },
  })
  const onDelete = () => Modal.confirm({
    title: '删除这个智能体？', content: '会话、消息与运行记录会一并删除，不可恢复。', okText: '删除', okButtonProps: { danger: true },
    onOk: async () => { try { await deleteAgent(agentId); setDirty(false); message.success('已删除'); navigate('/agents') } catch (e) { message.error(errorText(e, '删除失败')) } },
  })

  if (detail.error) {
    return <div style={{ flex: 1, minHeight: 0, overflow: 'auto' }}><ErrorState message={detail.error} onRetry={() => detail.reload()} /><div style={{ textAlign: 'center' }}><Button onClick={() => navigate('/agents')}>返回智能体列表</Button></div></div>
  }
  if (!agent) return <Skeleton active />

  return (
    <div style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column', gap: 12 }}>
      <EditorHeader agent={agent} dirty={dirty} saving={saving} compact={compact} onBack={() => guardedNavigate(`/agents/${agentId}`)} onSave={() => form.submit()}
        onPublish={() => setPublishOpen(true)} onOpenDetail={() => guardedNavigate(`/agents/${agentId}`)} onOffline={onOffline} onDelete={onDelete} />
      {options.error && <ErrorState compact message={options.error} onRetry={() => options.reload()} />}
      {compact && <Segmented block style={{ flexShrink: 0 }} value={pane} onChange={(v) => setPane(v as 'config' | 'debug')} options={[{ label: '配置', value: 'config' }, { label: '调试', value: 'debug' }]} />}
      <div style={{ flex: 1, minHeight: 0, display: 'flex', gap: 12 }}>
        {!compact && (
          <div style={{ width: 132, flexShrink: 0 }}>
            <Anchor replace affix={false} getContainer={() => scrollRef.current ?? window} items={EDITOR_SECTIONS.map((s) => ({ key: s.key, href: `#${sectionId(s.key)}`, title: s.title }))} />
          </div>
        )}
        {/* 移动端切到"调试"时配置区只隐藏不卸载：调试取的是表单里的当前内容 */}
        <div ref={scrollRef} style={{ flex: 1, minWidth: 0, minHeight: 0, overflow: 'auto', display: compact && pane === 'debug' ? 'none' : undefined }}>
          <Form form={form} layout="vertical" onFinish={onSave} onValuesChange={onValuesChange} scrollToFirstError>
            <ConfigSections form={form} models={models?.items ?? []} templates={templates?.items ?? []}
              kbOptions={(kbs?.items ?? []).map((k) => ({ value: k.id, label: k.name }))}
              toolOptions={(tools?.items ?? []).map((t) => ({ value: t.id, label: t.is_enabled ? t.name : `${t.name}（已停用）` }))}
              onRenderTemplate={renderPromptTemplate} />
          </Form>
        </div>
        {(compact ? pane === 'debug' : debugOpen) ? (
          <div style={{ width: compact ? undefined : 440, flex: compact ? 1 : undefined, flexShrink: 0, minWidth: 0, minHeight: 0, display: 'flex' }}>
            <DebugPanel messages={debug.messages} sending={debug.sending} compact={compact} onSend={debug.send} onStop={debug.stop}
              onRegenerate={debug.regenerate} onClear={debug.clear} onCollapse={compact ? undefined : () => setDebugOpen(false)} />
          </div>
        ) : !compact && <Button icon={<MenuFoldOutlined />} style={{ flexShrink: 0 }} onClick={() => setDebugOpen(true)}>调试</Button>}
      </div>
      <PublishModal agent={publishOpen ? agent : null} names={names} onClose={() => setPublishOpen(false)} onPublish={onPublish} />
    </div>
  )
}
