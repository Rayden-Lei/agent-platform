import { useEffect, useState } from 'react'
import { CircleCheck, CircleX } from 'lucide-react'
import type { KbAccess, KbAccessChange, KbAccessInput, KnowledgeBaseDetail } from '../../api'
import { statusOptions } from '../../constants/status'
import ResourceLink from '../common/ResourceLink'
import Button from '../ui/Button'
import Badge from '../ui/Badge'
import { Switch } from '@/components/shadcn/switch'
import { Label } from '@/components/shadcn/label'
import KbAccessLog from './KbAccessLog'

// 知识库详情的"访问权限"页签（docs/15 KB-01）：改规则（保存即生效，不用重新解析）、各身份能否检索的直白说明、
// "已发布却让调用者检索不到"的智能体提醒、变更记录。取数与保存都在 KbDetail 页面，本组件只接收 props。
interface Props {
  kb: KnowledgeBaseDetail
  myRole?: string
  saving: boolean
  onSave: (policy: KbAccessInput) => void
  changes: KbAccessChange[] | null
  changesTotal?: number
  changesError?: string | null
  onRetryChanges: () => void
}

// "谁能检索"逐行说明；文字说的是对话与检索评测里的实际效果，不是抽象的权限名词
const WHO: { key: keyof KbAccess; label: string; yes: string; no: string }[] = [
  { key: 'admin', label: '管理员', yes: '始终能检索、能管理', no: '' },
  { key: 'developer', label: '开发者', yes: '能在管理页看到、编辑、检索这个知识库', no: '看不到这个知识库，管理页和检索评测都是"不存在"' },
  { key: 'caller', label: '调用者', yes: '对话时智能体能引用这个知识库', no: '对话时智能体引用不到这个知识库（回答里不会出现它的内容）' },
  { key: 'anonymous', label: '匿名访客', yes: '通过分享链接对话时能引用（分享功能上线后）', no: '通过分享链接对话时引用不到' },
]

export default function KbAccessTab({ kb, myRole, saving, onSave, changes, changesTotal, changesError, onRetryChanges }: Props) {
  const [isPublic, setIsPublic] = useState(kb.is_public)
  const [roles, setRoles] = useState<string[]>(kb.visible_roles || [])
  // 保存成功后详情会重新取回，以服务端的值为准
  useEffect(() => { setIsPublic(kb.is_public); setRoles(kb.visible_roles || []) }, [kb.is_public, kb.visible_roles])
  const dirty = isPublic !== kb.is_public || (!isPublic && [...roles].sort().join() !== [...(kb.visible_roles || [])].sort().join())
  // 非管理员不能把自己排除在外：服务端同样拦（400），这里提前说明原因
  const shutsMeOut = myRole !== 'admin' && !isPublic && !roles.includes(myRole || '')
  const blindAgents = kb.access.caller ? [] : kb.agents.filter((a) => a.in_live && a.status === 'published')
  const toggleRole = (role: string) => setRoles((cur) => (cur.includes(role) ? cur.filter((r) => r !== role) : [...cur, role]))

  return (
    <div className="flex flex-col gap-3">
      {blindAgents.length > 0 && (
        <div className="flex flex-col gap-2 rounded-xl border border-border bg-card px-3 py-2.5">
          <div className="flex items-center gap-2">
            <Badge tone="warning">注意</Badge>
            <span className="text-[13.5px]">以下已发布的智能体线上版本绑定了本库，但调用者检索不到它</span>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {blindAgents.map((a) => <ResourceLink key={a.id} type="agent" id={a.id} name={a.name} showIcon />)}
          </div>
        </div>
      )}

      <section className="rounded-xl border border-border bg-card">
        <div className="border-b border-border px-4 py-2.5">
          <h3 className="m-0 text-[13.5px] font-semibold">访问规则</h3>
        </div>
        <div className="flex flex-col gap-3 px-4 py-3">
          <div className="flex items-center gap-2.5">
            <Switch id="kb-public" checked={isPublic} onCheckedChange={setIsPublic} />
            <Label htmlFor="kb-public" className="font-normal">公开（所有角色可见）</Label>
          </div>

          {!isPublic && (
            <div className="flex flex-col gap-1.5">
              <Label>可见角色（管理员始终可见）</Label>
              <div className="flex flex-wrap gap-1.5">
                {statusOptions('role').map((r) => {
                  const on = roles.includes(r.value)
                  return (
                    <Button key={r.value} size="sm" variant={on ? 'primary' : 'secondary'} onClick={() => toggleRole(r.value)}>
                      {r.label}
                    </Button>
                  )
                })}
              </div>
            </div>
          )}

          {shutsMeOut && (
            <p className="m-0 rounded-lg border border-destructive/35 bg-card px-3 py-2 text-[12.5px] text-destructive">
              不能把自己的角色排除在外：保存后你将看不到、也改不回这个知识库
            </p>
          )}

          <div className="flex flex-wrap items-center gap-2">
            <Button variant="primary" size="md" disabled={saving || !dirty || shutsMeOut} onClick={() => onSave({ is_public: isPublic, visible_roles: isPublic ? [] : roles })}>
              {saving ? '保存中…' : '保存'}
            </Button>
            <span className="text-[12.5px] text-muted-foreground">保存后立即生效，已入库的切片不用重新解析</span>
          </div>
        </div>
      </section>

      <section className="rounded-xl border border-border bg-card">
        <div className="border-b border-border px-4 py-2.5">
          <h3 className="m-0 text-[13.5px] font-semibold">现在谁能检索</h3>
        </div>
        <div className="flex flex-col gap-2 px-4 py-3">
          {WHO.map((w) => (
            <div key={w.key} className="flex items-start gap-2 text-[13.5px]">
              {kb.access[w.key]
                ? <CircleCheck className="mt-0.5 size-4 shrink-0 text-primary" aria-label="可以" />
                : <CircleX className="mt-0.5 size-4 shrink-0 text-destructive" aria-label="不可以" />}
              <span className="min-w-0">
                <span className="font-medium">{w.label}</span>
                <span className="ml-2 text-muted-foreground">{kb.access[w.key] ? w.yes : w.no}</span>
              </span>
            </div>
          ))}
        </div>
      </section>

      <KbAccessLog changes={changes} total={changesTotal} error={changesError} onRetry={onRetryChanges} />
    </div>
  )
}
