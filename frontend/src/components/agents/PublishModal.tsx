import { useEffect, useState } from 'react'
import { Alert, Input, Modal, Typography } from 'antd'
import type { AgentDetail } from '../../api'
import SnapshotDiff, { type RefNames } from './SnapshotDiff'

// 发布确认弹窗（docs/15 3.2）：线上与草稿的字段级差异 + 发布说明 + 预检。发布的是已保存的草稿；
// 预检里会被后端拒绝的（模型不可用、引用已删除）直接拦住，其余只提示。请求由页面注入（组件不发请求）。
interface Props {
  agent: AgentDetail | null // 非空即打开
  names?: RefNames
  onClose: () => void
  onPublish: (note?: string) => Promise<void> // 页面负责请求、提示与刷新；失败时抛出，弹窗保持打开
}

interface Check { type: 'error' | 'warning' | 'info'; text: string }

function prechecks(a: AgentDetail): Check[] {
  const checks: Check[] = []
  if (!a.model) checks.push({ type: 'error', text: '绑定的模型已删除，先在装配页换一个模型' })
  else if (!a.model.is_enabled) checks.push({ type: 'error', text: `模型「${a.model.name}」已停用，发布会被拒绝` })
  if (a.missing_tool_ids.length) checks.push({ type: 'error', text: `引用的工具已删除：#${a.missing_tool_ids.join('、#')}，先在装配页去掉` })
  if (a.missing_kb_ids.length) checks.push({ type: 'error', text: `引用的知识库已删除：#${a.missing_kb_ids.join('、#')}，先在装配页去掉` })
  const disabledTools = a.tools.filter((t) => !t.is_enabled).map((t) => t.name)
  if (disabledTools.length) checks.push({ type: 'warning', text: `这些工具已停用，发布后也不会提供给模型：${disabledTools.join('、')}` })
  if (a.prompt_template_outdated && a.prompt_template) {
    checks.push({ type: 'warning', text: `模板「${a.prompt_template.name}」已有 v${a.prompt_template.version}，草稿按 v${a.prompt_template_version} 渲染；要用新版先重新保存草稿` })
  }
  return checks
}

export default function PublishModal({ agent, names, onClose, onPublish }: Props) {
  const [note, setNote] = useState('')
  const [submitting, setSubmitting] = useState(false)
  useEffect(() => { if (agent) setNote('') }, [agent])
  if (!agent) return null

  const checks = prechecks(agent)
  const blocked = checks.some((c) => c.type === 'error')
  const reOnline = agent.status === 'offline' && !agent.has_unpublished_changes
  const nothingToDo = agent.status === 'published' && !agent.has_unpublished_changes
  const submit = async () => {
    setSubmitting(true)
    try { await onPublish(note.trim() || undefined) } catch { /* 页面已提示错误，弹窗保持打开便于修改后重试 */ } finally { setSubmitting(false) }
  }

  return (
    <Modal
      open
      title={reOnline ? `重新上线：${agent.name}` : `发布：${agent.name}`}
      okText={reOnline ? '重新上线' : '发布'}
      onOk={submit}
      onCancel={onClose}
      confirmLoading={submitting}
      okButtonProps={{ disabled: blocked || nothingToDo }}
      width={860}
      destroyOnHidden
      styles={{ body: { maxHeight: '60vh', overflow: 'auto' } }}
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        <Typography.Text type="secondary">
          {reOnline
            ? '草稿与下线前的线上版本一致：确认后原样重新上线，不生成新版本。'
            : '发布后草稿成为新的线上版本，对话、API Key、工作流从下一轮起按它回答；每次发布都生成一个可回滚的版本。'}
          引用的工具、知识库、模型本身的修改不经发布，一直是立即生效的。
        </Typography.Text>
        {nothingToDo && <Alert type="info" showIcon message="草稿与线上一致，无需发布" />}
        {checks.map((c) => <Alert key={c.text} type={c.type} showIcon message={c.text} />)}
        {!reOnline && !nothingToDo && (
          agent.live_snapshot
            ? <div><Typography.Text strong>线上 v{agent.published_version} → 草稿的差异</Typography.Text><div style={{ marginTop: 8 }}><SnapshotDiff before={agent.live_snapshot} after={agent.draft_snapshot} names={names} /></div></div>
            : <Alert type="info" showIcon message="首次发布，将生成 v1" />
        )}
        <Input.TextArea value={note} onChange={(e) => setNote(e.target.value)} maxLength={200} showCount autoSize={{ minRows: 2, maxRows: 4 }}
          placeholder="发布说明（可选）：改了什么、为什么，进版本历史与审计" disabled={nothingToDo} />
      </div>
    </Modal>
  )
}
