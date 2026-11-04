import type { ApiKeyRow } from '../../api'
import type { DataColumn } from '../table/DataTable'
import Badge from '../ui/Badge'
import Button from '../ui/Button'
import InlineConfirm from '../ui/InlineConfirm'
import EnableSwitch from '../common/EnableSwitch'
import TimeCell from '../common/TimeCell'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/shadcn/tooltip'

interface Options {
  isAdmin: boolean
  onOpen: (k: ApiKeyRow) => void
  onToggle: (k: ApiKeyRow) => Promise<unknown>
  onEdit: (k: ApiKeyRow) => void
  onDelete: (k: ApiKeyRow) => void
}

// 配额进度：用量占比 ≥ 90% 标红提醒续配额
export function QuotaCell({ used, quota }: { used: number; quota: number }) {
  if (!quota) return <span className="text-muted-foreground">{used} / 不限</span>
  const ratio = Math.min(used / quota, 1)
  const danger = ratio >= 0.9
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <div className="min-w-[120px] cursor-default">
          <div className="h-1.5 w-full overflow-hidden rounded-full bg-secondary">
            <div className="h-full rounded-full" style={{ width: `${Math.round(ratio * 100)}%`, background: danger ? 'var(--danger)' : 'var(--accent)' }} />
          </div>
          <span className="mt-0.5 block text-[11.5px] text-muted-foreground">{used} / {quota}</span>
        </div>
      </TooltipTrigger>
      <TooltipContent>已用 {used} / 配额 {quota}</TooltipContent>
    </Tooltip>
  )
}

// 授权范围（docs/15 3.7.1）：N 个智能体、M 个工作流…，悬停看名称，已删除的资源标"已删除"；三类都空的是迁移前建的，调用一律被拒
const SCOPE_LABELS = [['agents', '智能体'], ['workflows', '工作流'], ['knowledge_bases', '知识库']] as const
export function ScopeCell({ scope }: { scope: ApiKeyRow['scope'] }) {
  const parts = SCOPE_LABELS.filter(([key]) => scope[key].length)
  if (!parts.length) {
    return (
      <Tooltip>
        <TooltipTrigger asChild><span><Badge tone="warning">未授权</Badge></span></TooltipTrigger>
        <TooltipContent>没有授权任何资源（迁移前建的 Key），调用一律被拒；编辑后授权即可</TooltipContent>
      </Tooltip>
    )
  }
  const names = parts.map(([key, label]) => `${label}：${scope[key].map((x) => x.name ?? `已删除 #${x.id}`).join('、')}`)
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span className="cursor-default">{parts.map(([key, label]) => `${scope[key].length} 个${label}`).join('、')}</span>
      </TooltipTrigger>
      <TooltipContent className="whitespace-pre-line">{names.join('\n')}</TooltipContent>
    </Tooltip>
  )
}

// API Key 列表列定义：Key 只显示前缀；配额用进度条；admin 视角多一列归属。
export function buildApiKeyColumns({ isAdmin, onOpen, onToggle, onEdit, onDelete }: Options): DataColumn<ApiKeyRow>[] {
  const columns: DataColumn<ApiKeyRow>[] = [
    { key: 'id', header: 'ID', width: 64, sortable: true, cell: (r) => <span className="text-muted-foreground">{r.id}</span> },
    {
      key: 'name', header: '名称', primary: true, sortable: true, width: 200,
      cell: (r) => <button type="button" onClick={() => onOpen(r)} className="truncate text-left font-medium text-primary hover:underline">{r.name}</button>,
    },
    { key: 'scope', header: '授权范围', width: 170, hideOnMobile: true, cell: (r) => <ScopeCell scope={r.scope} /> },
    { key: 'key_prefix', header: 'Key 前缀', width: 130, hideOnMobile: true, cell: (r) => <code className="font-mono text-[12.5px]">{r.key_prefix}…</code> },
  ]
  if (isAdmin) {
    columns.push({ key: 'username', header: '归属', width: 110, hideOnMobile: true, cell: (r) => r.username || <span className="text-muted-foreground">-</span> })
  }
  columns.push(
    { key: 'quota', header: '配额 / 已用', width: 170, cell: (r) => <QuotaCell used={r.used} quota={r.quota} /> },
    {
      key: 'allowed_ips', header: '来源限制', width: 110, hideOnMobile: true,
      cell: (r) => (r.allowed_ips.length === 0 ? <span className="text-muted-foreground">不限制</span> : (
        <Tooltip>
          <TooltipTrigger asChild><span><Badge tone="neutral">{r.allowed_ips.length} 条</Badge></span></TooltipTrigger>
          <TooltipContent className="whitespace-pre-line font-mono">{r.allowed_ips.join('\n')}</TooltipContent>
        </Tooltip>
      )),
    },
    { key: 'rate_limit_per_minute', header: '限速 / 分钟', width: 110, align: 'right', hideOnMobile: true, cell: (r) => (r.rate_limit_per_minute === 0 ? <span className="text-muted-foreground">默认</span> : r.rate_limit_per_minute) },
    { key: 'status', header: '状态', width: 80, cell: (r) => <EnableSwitch checked={r.is_enabled} onToggle={() => onToggle(r)} /> },
    { key: 'last_used_at', header: '最后使用', width: 120, sortable: true, hideOnMobile: true, cell: (r) => <TimeCell value={r.last_used_at} mode="relative" /> },
    { key: 'created_at', header: '创建时间', width: 168, sortable: true, hideOnMobile: true, cell: (r) => <TimeCell value={r.created_at} /> },
    {
      key: 'actions', header: '操作', width: 150, pinRight: true,
      cell: (r) => (
        <span className="inline-flex items-center gap-1.5" onClick={(e) => e.stopPropagation()}>
          <Button size="sm" variant="secondary" onClick={() => onEdit(r)}>编辑</Button>
          <InlineConfirm message="确定删除？使用该 Key 的调用会立即失效" onConfirm={() => onDelete(r)}>
            <Button size="sm" variant="danger">删除</Button>
          </InlineConfirm>
        </span>
      ),
    },
  )
  return columns
}
