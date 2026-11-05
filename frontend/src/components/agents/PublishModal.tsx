import { useEffect, useState } from 'react'
import { AlertTriangle, Info, XCircle } from 'lucide-react'
import { Label } from '@/components/shadcn/label'
import { Textarea } from '@/components/shadcn/textarea'
import Modal from '../ui/Modal'
import Button from '../ui/Button'
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
  if (a.missing_skill_ids.length) checks.push({ type: 'error', text: `引用的技能已删除：#${a.missing_skill_ids.join('、#')}，先在装配页去掉` })
  const disabledTools = a.tools.filter((t) => !t.is_enabled).map((t) => t.name)
  if (disabledTools.length) checks.push({ type: 'warning', text: `这些工具已停用，发布后也不会提供给模型：${disabledTools.join('、')}` })
  // 技能停用只影响装配（不提供给模型），绑定关系保留；与工具同一口径只提示，不拦发布
  const disabledSkills = a.skills.filter((s) => !s.is_enabled).map((s) => s.display_name)
  if (disabledSkills.length) checks.push({ type: 'warning', text: `这些技能已停用，发布后也不会提供给模型：${disabledSkills.join('、')}` })
  if (a.prompt_template_outdated && a.prompt_template) {
    checks.push({ type: 'warning', text: `模板「${a.prompt_template.name}」已有 v${a.prompt_template.version}，草稿按 v${a.prompt_template_version} 渲染；要用新版先重新保存草稿` })
  }
  return checks
}

// 预检条目：错误拦住发布（红），警告与提示只说明情况（灰底 + 中性图标），不用满屏彩色条
function Notice({ tone, text }: { tone: Check['type']; text: string }) {
  const Icon = tone === 'error' ? XCircle : tone === 'warning' ? AlertTriangle : Info
  return (
    <div className="flex items-start gap-2 rounded-lg border border-border bg-secondary px-3 py-2">
      <Icon className={tone === 'error' ? 'mt-0.5 size-4 shrink-0 text-destructive' : 'mt-0.5 size-4 shrink-0 text-muted-foreground'} aria-hidden="true" />
      <span className={tone === 'error' ? 'text-[12.5px] leading-snug text-destructive' : 'text-[12.5px] leading-snug text-foreground'}>{text}</span>
    </div>
  )
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
      size="lg"
      title={reOnline ? `重新上线：${agent.name}` : `发布：${agent.name}`}
      onClose={onClose}
      footer={
        <>
          <Button variant="ghost" size="md" onClick={onClose}>取消</Button>
          <Button variant="primary" size="md" disabled={blocked || nothingToDo || submitting} onClick={submit}>
            {submitting ? '处理中…' : reOnline ? '重新上线' : '发布'}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-3">
        <p className="m-0 text-[12.5px] leading-relaxed text-muted-foreground">
          {reOnline
            ? '草稿与下线前的线上版本一致：确认后原样重新上线，不生成新版本。'
            : '发布后草稿成为新的线上版本，对话、API Key、工作流从下一轮起按它回答；每次发布都生成一个可回滚的版本。'}
          引用的工具、知识库、模型本身的修改不经发布，一直是立即生效的。
        </p>

        {nothingToDo && <Notice tone="info" text="草稿与线上一致，无需发布" />}
        {checks.map((c) => <Notice key={c.text} tone={c.type} text={c.text} />)}

        {!reOnline && !nothingToDo && (
          agent.live_snapshot ? (
            <div className="flex flex-col gap-2">
              <h3 className="m-0 text-[13px] font-medium text-foreground">线上 v{agent.published_version} → 草稿的差异</h3>
              <SnapshotDiff before={agent.live_snapshot} after={agent.draft_snapshot} names={names} />
            </div>
          ) : <Notice tone="info" text="首次发布，将生成 v1" />
        )}

        <div className="flex flex-col gap-1.5">
          <Label htmlFor="publish-note">发布说明（可选）</Label>
          <Textarea
            id="publish-note"
            rows={2}
            maxLength={200}
            value={note}
            disabled={nothingToDo}
            onChange={(e) => setNote(e.target.value)}
            placeholder="改了什么、为什么，进版本历史与审计"
            className="resize-y text-[13px]"
          />
          <p className="m-0 self-end text-[12px] text-muted-foreground">{note.length}/200</p>
        </div>
      </div>
    </Modal>
  )
}
