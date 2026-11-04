import { Link } from 'react-router-dom'
import type { ModelBreakerStatus, ModelRow, ModelUsageRow } from '../../api'
import type { DataColumn, SortState } from '../table/DataTable'
import Badge from '../ui/Badge'
import Button from '../ui/Button'
import InlineConfirm from '../ui/InlineConfirm'
import EnableSwitch from '../common/EnableSwitch'
import StatusTag from '../common/StatusTag'
import TimeCell from '../common/TimeCell'
import { formatCost, formatNumber } from '../../utils/format'

interface Options {
  sort: SortState
  breakers: Record<number, ModelBreakerStatus>
  usage: Record<number, ModelUsageRow>
  testingId: number | null
  canManage: boolean
  onOpen: (model: ModelRow) => void
  onToggle: (model: ModelRow) => Promise<unknown>
  onTest: (model: ModelRow) => void
  onEdit: (model: ModelRow) => void
  onDelete: (model: ModelRow) => void
}

// 熔断标签：open 显示重试倒计时，half_open 表示正在放行探测请求
export function BreakerTag({ breaker }: { breaker: ModelBreakerStatus | { state: string; consecutive_failures: number; retry_after_seconds: number } | null | undefined }) {
  if (!breaker || breaker.state === 'closed') return null
  return (
    <span
      className="inline-flex items-center gap-1"
      title={`连续失败 ${breaker.consecutive_failures} 次；连通测试成功后立即恢复`}
    >
      <StatusTag domain="breaker" value={breaker.state} />
      {breaker.state === 'open' && <span className="text-[12px]" style={{ color: 'var(--fg-subtle)' }}>{breaker.retry_after_seconds}s 后重试</span>}
    </span>
  )
}

// 价格列：元 / 百万 token，未配置显示"-"并提示成本统计不可用
export function priceText(input: number | null, output: number | null): string {
  if (input === null && output === null) return '-'
  return `${input ?? '-'} / ${output ?? '-'}`
}

// 模型列表列定义：名称打开抽屉；状态列为启停开关 + 熔断标签；近 7 天用量来自 /stats/models。
export function buildModelColumns({ breakers, usage, testingId, canManage, onOpen, onToggle, onTest, onEdit, onDelete }: Options): DataColumn<ModelRow>[] {
  return [
    { key: 'id', header: 'ID', width: 64, sortable: true, cell: (r) => <span style={{ color: 'var(--fg-muted)' }}>{r.id}</span> },
    {
      key: 'name', header: '名称', sortable: true, primary: true, width: 180,
      cell: (r) => (
        <button type="button" onClick={(e) => { e.stopPropagation(); onOpen(r) }} className="hover:underline text-left truncate" style={{ color: 'var(--fg)', fontWeight: 550 }}>
          {r.name}
        </button>
      ),
    },
    { key: 'provider', header: '提供商', width: 110, sortable: true, hideOnMobile: true, cell: (r) => <StatusTag domain="provider" value={r.provider} /> },
    { key: 'model_name', header: '模型名', width: 170, hideOnMobile: true, cell: (r) => <span className="truncate block" style={{ color: 'var(--fg-muted)' }}>{r.model_name}</span> },
    {
      key: 'price', header: '价格（元/百万 token）', width: 168, align: 'right', hideOnMobile: true,
      cell: (r) => (r.price_input === null && r.price_output === null
        ? <Badge tone="warning" title="未配置价格，运行成本按 0 计">未配置</Badge>
        : <span style={{ fontVariantNumeric: 'tabular-nums' }}>{priceText(r.price_input, r.price_output)}</span>),
    },
    {
      key: 'status', header: '状态', width: 190,
      cell: (r) => (
        <span className="inline-flex items-center gap-1.5 flex-wrap">
          <EnableSwitch checked={r.is_enabled} disabled={!canManage} onToggle={() => onToggle(r)} />
          <BreakerTag breaker={breakers[r.id]} />
        </span>
      ),
    },
    {
      key: 'agents_count', header: '智能体', width: 80, align: 'right', hideOnMobile: true,
      cell: (r) => (r.agents_count
        ? <Link to={`/agents?model_id=${r.id}`} onClick={(e) => e.stopPropagation()} style={{ color: 'var(--accent)' }}>{r.agents_count}</Link>
        : <span style={{ color: 'var(--fg-subtle)' }}>0</span>),
    },
    {
      key: 'usage', header: '近 7 天 运行/Token/成本', width: 200, align: 'right', hideOnMobile: true,
      cell: (r) => {
        const u = usage[r.id]
        return u && u.total
          ? <span style={{ fontVariantNumeric: 'tabular-nums' }}>{`${u.total} / ${formatNumber(u.total_tokens)} / ${formatCost(u.cost)}`}</span>
          : <span style={{ color: 'var(--fg-subtle)' }}>-</span>
      },
    },
    { key: 'created_by_username', header: '创建人', width: 96, hideOnMobile: true, cell: (r) => r.created_by_username || <span style={{ color: 'var(--fg-subtle)' }}>-</span> },
    { key: 'updated_at', header: '更新时间', width: 168, sortable: true, hideOnMobile: true, cell: (r) => <TimeCell value={r.updated_at} /> },
    {
      key: 'actions', header: '操作', width: 200, pinRight: true,
      cell: (r) => (
        <span className="inline-flex items-center gap-1.5" onClick={(e) => e.stopPropagation()}>
          <Button size="sm" variant="secondary" onClick={() => onTest(r)}>{testingId === r.id ? '测试中…' : '测试'}</Button>
          <Button size="sm" variant="secondary" disabled={!canManage} onClick={() => onEdit(r)}>编辑</Button>
          <InlineConfirm message="确定删除？绑定了该模型的智能体将无法对话" onConfirm={() => onDelete(r)}>
            <Button size="sm" variant="danger" disabled={!canManage}>删除</Button>
          </InlineConfirm>
        </span>
      ),
    },
  ]
}
