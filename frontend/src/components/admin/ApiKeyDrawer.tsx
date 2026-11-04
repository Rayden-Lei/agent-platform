import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { TriangleAlert } from 'lucide-react'
import { Alert, AlertDescription, AlertTitle } from '@/components/shadcn/alert'
import type { ApiKeyRow, ApiKeyScopeItem } from '../../api'
import type { ResourceType } from '../../constants/resources'
import ResourceLink from '../common/ResourceLink'
import StatusTag from '../common/StatusTag'
import TimeCell from '../common/TimeCell'
import Drawer from '../ui/Drawer'
import Button from '../ui/Button'
import { QuotaCell } from './apiKeyColumns'

// API Key 详情抽屉：授权范围、配额与用量、来源白名单全文、限速、归属与时间；密钥本身不可再查看。
interface Props { apiKey: ApiKeyRow | null; onClose: () => void; onEdit: (k: ApiKeyRow) => void }

// 详情字段：标签在上、值在下（替代 antd Descriptions 的表格块）
function Field({ label, children, wide }: { label: string; children: ReactNode; wide?: boolean }) {
  return (
    <div className={wide ? 'col-span-2' : undefined}>
      <dt className="text-[12px] text-muted-foreground">{label}</dt>
      <dd className="m-0 mt-1 text-[13px] text-foreground">{children}</dd>
    </div>
  )
}

// 授权的资源逐个给跳转链接；已删除的资源没有详情可跳，标"已删除"
function ScopeList({ type, items }: { type: ResourceType; items: ApiKeyScopeItem[] }) {
  if (!items.length) return <span className="text-muted-foreground">无</span>
  return (
    <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
      {items.map((x) => (x.name === null
        ? <span key={x.id} className="rounded-full bg-secondary px-2 py-[1px] text-[11.5px] text-muted-foreground">已删除 #{x.id}</span>
        : <ResourceLink key={x.id} type={type} id={x.id} name={x.name} showIcon />))}
    </span>
  )
}

export default function ApiKeyDrawer({ apiKey: k, onClose, onEdit }: Props) {
  return (
    <Drawer
      open={!!k}
      width={720}
      title={k ? `API Key：${k.name}` : ''}
      onClose={onClose}
      extra={k && <Button variant="primary" onClick={() => onEdit(k)}>编辑</Button>}
    >
      {k && (
        <div className="flex flex-col gap-4">
          {!k.agent_ids.length && !k.workflow_ids.length && !k.kb_ids.length && (
            <Alert className="border-border-strong">
              <TriangleAlert className="text-muted-foreground" />
              <AlertTitle>这个 Key 没有授权任何资源，调用一律被拒</AlertTitle>
              <AlertDescription>它是作用域上线（2026-10-05）之前建的；点右上角“编辑”授权要调用的智能体或工作流后即可使用。</AlertDescription>
            </Alert>
          )}

          <section className="flex flex-col gap-2">
            <h3 className="m-0 text-[13px] font-semibold text-foreground">授权范围</h3>
            <dl className="m-0 grid grid-cols-2 gap-x-4 gap-y-3 rounded-lg border border-border bg-card p-3.5">
              <Field label="可调用的智能体" wide><ScopeList type="agent" items={k.scope.agents} /></Field>
              <Field label="可运行的工作流" wide><ScopeList type="workflow" items={k.scope.workflows} /></Field>
              <Field label="检索放行的知识库" wide><ScopeList type="kb" items={k.scope.knowledge_bases} /></Field>
            </dl>
          </section>

          <dl className="m-0 grid grid-cols-2 gap-x-4 gap-y-3 rounded-lg border border-border bg-card p-3.5">
            <Field label="Key 前缀"><span className="font-mono">{k.key_prefix}…</span></Field>
            <Field label="状态"><StatusTag domain="enabled" value={k.is_enabled} /></Field>
            <Field label="配额 / 已用" wide><QuotaCell used={k.used} quota={k.quota} /></Field>
            <Field label="每分钟限速">{k.rate_limit_per_minute === 0 ? '服务端默认' : k.rate_limit_per_minute}</Field>
            <Field label="归属">{k.username || '-'}</Field>
            <Field label="最后使用"><TimeCell value={k.last_used_at} /></Field>
            <Field label="创建时间"><TimeCell value={k.created_at} /></Field>
          </dl>

          <section className="flex flex-col gap-2">
            <h3 className="m-0 text-[13px] font-semibold text-foreground">
              允许的来源 IP（{k.allowed_ips.length ? k.allowed_ips.length + ' 条' : '不限制'}）
            </h3>
            {k.allowed_ips.length ? (
              <div className="flex flex-wrap gap-1.5">
                {k.allowed_ips.map((ip) => (
                  <span key={ip} className="rounded-full bg-secondary px-2 py-[1px] font-mono text-[11.5px] text-foreground">{ip}</span>
                ))}
              </div>
            ) : (
              <p className="m-0 text-[13px] text-muted-foreground">任何来源都可使用；建议生产环境限定 CIDR</p>
            )}
          </section>

          <p className="m-0 text-[12px] leading-relaxed text-muted-foreground">
            密钥明文只在生成时显示一次，无法找回；泄露时请删除并重新生成。通过该 Key 发起的运行在
            <Link to="/runs?source=api_key" className="text-primary hover:underline">运行记录</Link>
            里按"API Key"来源筛选。
          </p>
        </div>
      )}
    </Drawer>
  )
}
