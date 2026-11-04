import { Copy, Pencil, Play } from 'lucide-react'
import { Link } from 'react-router-dom'
import type { WorkflowRow } from '../../api'
import type { DataColumn } from '../table/DataTable'
import Badge from '../ui/Badge'
import Button from '../ui/Button'
import InlineConfirm from '../ui/InlineConfirm'
import StatusTag from '../common/StatusTag'
import TimeCell from '../common/TimeCell'
import { paletteOf } from '../../pages/workflow/palette'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/shadcn/tooltip'

interface Options {
  onRun: (wf: WorkflowRow) => void
  onDuplicate: (wf: WorkflowRow) => void
  onDelete: (wf: WorkflowRow) => void
}

// 节点类型统计的中文摘要：把 {agent: 2, tool: 1} 变成 "智能体 2 · 工具 1"
export function nodeTypeSummary(types: Record<string, number>): string {
  return Object.entries(types || {}).map(([t, n]) => `${paletteOf(t)?.label ?? t} ${n}`).join(' · ')
}

// 工作流列表列定义：名称进详情页；节点列显示数量与类型构成；近 7 天运行可跳运行记录。
export function buildWorkflowColumns({ onRun, onDuplicate, onDelete }: Options): DataColumn<WorkflowRow>[] {
  return [
    { key: 'id', header: 'ID', width: 64, sortable: true, cell: (r) => <span className="text-muted-foreground">{r.id}</span> },
    {
      key: 'name', header: '名称', primary: true, sortable: true, width: 220,
      cell: (r) => <Link to={`/workflows/${r.id}`} onClick={(e) => e.stopPropagation()} className="font-medium hover:underline" style={{ color: 'var(--fg)' }}>{r.name}</Link>,
    },
    { key: 'description', header: '描述', hideOnMobile: true, cell: (r) => r.description || <span className="text-muted-foreground">-</span> },
    { key: 'status', header: '状态', width: 92, sortable: true, cell: (r) => <StatusTag domain="workflow" value={r.status} /> },
    { key: 'version', header: '版本', width: 70, hideOnMobile: true, cell: (r) => `v${r.version}` },
    {
      key: 'node_count', header: '节点', width: 90, align: 'right', hideOnMobile: true,
      cell: (r) => (r.node_count ? (
        <Tooltip>
          <TooltipTrigger asChild><span className="cursor-help underline decoration-dotted underline-offset-2">{r.node_count}</span></TooltipTrigger>
          <TooltipContent>{nodeTypeSummary(r.node_types)}</TooltipContent>
        </Tooltip>
      ) : <Badge tone="neutral">空图</Badge>),
    },
    { key: 'schedules_count', header: '定时任务', width: 92, align: 'right', hideOnMobile: true, cell: (r) => (r.schedules_count || '-') },
    {
      key: 'runs_7d', header: '近 7 天运行', width: 110, align: 'right', hideOnMobile: true,
      cell: (r) => (r.runs_7d ? <Link to={`/runs?workflow_id=${r.id}`} className="text-primary hover:underline">{r.runs_7d}</Link> : <span className="text-muted-foreground">0</span>),
    },
    { key: 'last_run_at', header: '最近运行', width: 110, hideOnMobile: true, cell: (r) => <TimeCell value={r.last_run_at} mode="relative" /> },
    { key: 'created_by_username', header: '创建人', width: 100, hideOnMobile: true, cell: (r) => r.created_by_username || <span className="text-muted-foreground">-</span> },
    { key: 'updated_at', header: '更新时间', width: 168, sortable: true, hideOnMobile: true, cell: (r) => <TimeCell value={r.updated_at} /> },
    {
      key: 'actions', header: '操作', width: 300, pinRight: true,
      cell: (r) => (
        <span className="inline-flex items-center gap-1.5" onClick={(e) => e.stopPropagation()}>
          <Link to={`/workflows/${r.id}/edit`}><Button size="sm" variant="ghost" icon={<Pencil />}>编辑</Button></Link>
          <Button size="sm" variant="secondary" icon={<Play />} disabled={!r.node_count} onClick={() => onRun(r)}>运行</Button>
          <Button size="sm" variant="secondary" icon={<Copy />} onClick={() => onDuplicate(r)}>复制</Button>
          <InlineConfirm message="确定删除？关联的定时任务会一并删除" onConfirm={() => onDelete(r)}>
            <Button size="sm" variant="danger">删除</Button>
          </InlineConfirm>
        </span>
      ),
    },
  ]
}
