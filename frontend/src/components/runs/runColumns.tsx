import { Check, X } from 'lucide-react'
import { Link } from 'react-router-dom'
import type { RunRow } from '../../api'
import type { DataColumn } from '../table/DataTable'
import Button from '../ui/Button'
import ResourceLink from '../common/ResourceLink'
import StatusTag from '../common/StatusTag'
import TimeCell from '../common/TimeCell'
import TokenUsage from '../common/TokenUsage'
import { formatCost } from '../../utils/format'
import { formatDuration } from '../../utils/time'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/shadcn/tooltip'

// 运行记录的列定义：全局运行记录页与详情页里的嵌入表共用；sortable 的列由 DataTable 触发服务端排序。
interface Options {
  onReview?: (run: RunRow, decision: 'approved' | 'rejected') => void
  reviewing?: number | null
  hideOwner?: boolean // 详情页里已知归属，不重复显示
}

export function buildRunColumns({ onReview, reviewing, hideOwner = false }: Options): DataColumn<RunRow>[] {
  const columns: DataColumn<RunRow>[] = [
    { key: 'id', header: 'ID', width: 84, sortable: true, cell: (r) => <Link to={`/runs/${r.id}`} className="text-primary hover:underline">#{r.id}</Link> },
    { key: 'run_type', header: '类型', width: 90, cell: (r) => <StatusTag domain="runType" value={r.run_type} /> },
    { key: 'status', header: '状态', width: 110, cell: (r) => <StatusTag domain="run" value={r.status} /> },
  ]
  if (!hideOwner) {
    columns.push({
      key: 'owner', header: '归属', width: 180, hideOnMobile: true,
      cell: (r) => r.run_type === 'chat'
        ? <ResourceLink type="agent" id={r.agent_id} name={r.agent_name} />
        : <ResourceLink type="workflow" id={r.workflow_id} name={r.workflow_name} />,
    })
  }
  columns.push(
    {
      key: 'source', header: '触发', width: 150, hideOnMobile: true,
      cell: (r) => (
        <span className="inline-flex items-center gap-1">
          <StatusTag domain="runSource" value={r.source} />
          {r.username && <span className="text-muted-foreground">{r.username}</span>}
        </span>
      ),
    },
    { key: 'model_name', header: '模型', width: 140, hideOnMobile: true, cell: (r) => (r.model_name ? <ResourceLink type="model" id={r.model_id} name={r.model_name} /> : '-') },
    { key: 'tokens', header: 'Token', width: 100, align: 'right', hideOnMobile: true, cell: (r) => <TokenUsage usage={r.token_usage} cost={r.cost} compact /> },
    { key: 'cost', header: '成本', width: 100, align: 'right', sortable: true, hideOnMobile: true, cell: (r) => formatCost(r.cost) },
    { key: 'latency_ms', header: '耗时', width: 100, align: 'right', sortable: true, hideOnMobile: true, cell: (r) => (r.finished_at ? formatDuration(r.latency_ms) : '-') },
    { key: 'started_at', header: '开始时间', width: 170, sortable: true, cell: (r) => <TimeCell value={r.started_at} /> },
    {
      key: 'error', header: '错误', hideOnMobile: true,
      cell: (r) => (r.error ? (
        <Tooltip>
          <TooltipTrigger asChild><span className="block max-w-[220px] truncate text-destructive">{r.error}</span></TooltipTrigger>
          <TooltipContent className="max-w-md whitespace-pre-wrap">{r.error}</TooltipContent>
        </Tooltip>
      ) : '-'),
    },
  )
  if (onReview) {
    columns.push({
      key: 'actions', header: '操作', width: 160, pinRight: true,
      cell: (r) => r.status === 'awaiting_review' ? (
        <span className="inline-flex items-center gap-1.5" onClick={(e) => e.stopPropagation()}>
          <Button size="sm" variant="primary" icon={<Check />} disabled={reviewing === r.id} onClick={() => onReview(r, 'approved')}>通过</Button>
          <Button size="sm" variant="danger" icon={<X />} disabled={reviewing === r.id} onClick={() => onReview(r, 'rejected')}>拒绝</Button>
        </span>
      ) : <Link to={`/runs/${r.id}`} className="text-primary hover:underline">详情</Link>,
    })
  }
  return columns
}
