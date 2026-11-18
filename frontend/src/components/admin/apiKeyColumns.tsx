import type { ApiKeyRow } from '../../api'
import type { DataColumn } from '../table/DataTable'
import Badge from '../ui/Badge'
import Button from '../ui/Button'
import InlineConfirm from '../ui/InlineConfirm'
import EnableSwitch from '../common/EnableSwitch'
import TimeCell from '../common/TimeCell'
import { ExpiredBadge, QuotaCell, ScopeCell } from './apiKeyCells'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/shadcn/tooltip'

interface Options {
  isAdmin: boolean
  onOpen: (k: ApiKeyRow) => void
  onToggle: (k: ApiKeyRow) => Promise<unknown>
  onEdit: (k: ApiKeyRow) => void
  onDelete: (k: ApiKeyRow) => void
  onRotate: (k: ApiKeyRow) => void
}

// API Key 列表列定义：Key 只显示前缀；配额用进度条；admin 视角多一列归属。
// 配额、授权范围、过期徽章三件展示单元格在 ./apiKeyCells（详情抽屉、个人中心、发布渠道的小表也复用）。
export function buildApiKeyColumns({ isAdmin, onOpen, onToggle, onEdit, onDelete, onRotate }: Options): DataColumn<ApiKeyRow>[] {
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
    {
      key: 'status', header: '状态', width: 130,
      // 停用与过期是两件事，可以同时成立：开关表达 is_enabled，徽章表达 is_expired，并排显示不互相顶掉
      cell: (r) => (
        <span className="inline-flex items-center gap-1.5">
          <EnableSwitch checked={r.is_enabled} onToggle={() => onToggle(r)} />
          {r.is_expired && <ExpiredBadge expiresAt={r.expires_at} />}
        </span>
      ),
    },
    { key: 'expires_at', header: '有效期', width: 168, hideOnMobile: true, cell: (r) => (r.expires_at ? <TimeCell value={r.expires_at} /> : <span className="text-muted-foreground">永不过期</span>) },
    { key: 'last_used_at', header: '最后使用', width: 120, sortable: true, hideOnMobile: true, cell: (r) => <TimeCell value={r.last_used_at} mode="relative" /> },
    { key: 'created_at', header: '创建时间', width: 168, sortable: true, hideOnMobile: true, cell: (r) => <TimeCell value={r.created_at} /> },
    {
      key: 'actions', header: '操作', width: 210, pinRight: true,
      // 已过期的 Key 仍然给「编辑 / 轮换 / 删除」三件，而不是只留轮换：
      // 轮换只换明文，服务端会原样保留 expires_at，所以对过期 Key 轮换完它还是过期的；
      // 唯一能救活它的是编辑里的有效期（改到未来或清除）。把编辑藏掉等于把唯一的修复入口藏掉。
      // 这里把按钮文案改成「改有效期」，让过期 Key 的修复路径一眼可见。
      cell: (r) => (
        <span className="inline-flex items-center gap-1.5" onClick={(e) => e.stopPropagation()}>
          <Button size="sm" variant="secondary" onClick={() => onEdit(r)}>{r.is_expired ? '改有效期' : '编辑'}</Button>
          <Button size="sm" variant="secondary" onClick={() => onRotate(r)}>轮换</Button>
          <InlineConfirm message="确定删除？使用该 Key 的调用会立即失效" danger onConfirm={() => onDelete(r)}>
            <Button size="sm" variant="danger">删除</Button>
          </InlineConfirm>
        </span>
      ),
    },
  )
  return columns
}
