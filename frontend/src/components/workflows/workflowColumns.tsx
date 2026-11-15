import { Copy, Pencil, Play, Rocket } from 'lucide-react'
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
  onPublish: (wf: WorkflowRow) => void
  onDuplicate: (wf: WorkflowRow) => void
  onDelete: (wf: WorkflowRow) => void
}

// 节点类型统计的中文摘要：把 {agent: 2, tool: 1} 变成 "智能体 2 · 工具 1"
export function nodeTypeSummary(types: Record<string, number>): string {
  return Object.entries(types || {}).map(([t, n]) => `${paletteOf(t)?.label ?? t} ${n}`).join(' · ')
}

// 工作流列表列定义：名称进详情页；节点列显示数量与类型构成；近 7 天运行可跳运行记录。
// 版本列显示线上版本号（published_version）与"有未发布改动"：草稿修订号 version 只在编辑器里有意义，
// 列表里看线上是哪一版才是用户关心的（FR-075）。
export function buildWorkflowColumns({ onRun, onPublish, onDuplicate, onDelete }: Options): DataColumn<WorkflowRow>[] {
  return [
    { key: 'id', header: 'ID', width: 64, sortable: true, cell: (r) => <span className="text-muted-foreground">{r.id}</span> },
    {
      key: 'name', header: '名称', primary: true, sortable: true, width: 220,
      cell: (r) => <Link to={`/workflows/${r.id}`} onClick={(e) => e.stopPropagation()} className="font-medium hover:underline" style={{ color: 'var(--fg)' }}>{r.name}</Link>,
    },
    { key: 'description', header: '描述', hideOnMobile: true, cell: (r) => r.description || <span className="text-muted-foreground">-</span> },
    { key: 'status', header: '状态', width: 92, sortable: true, cell: (r) => <StatusTag domain="workflow" value={r.status} /> },
    {
      key: 'version', header: '线上版本', width: 132, sortable: true, hideOnMobile: true,
      cell: (r) => (
        <span className="inline-flex items-center gap-1.5">
          <span className="text-[13px]">{r.published_version ? `v${r.published_version}` : <span className="text-muted-foreground">未发布</span>}</span>
          {r.has_unpublished_changes && <Badge tone="warning" title={`草稿已改到修订 ${r.version}，发布后对外生效`}>未发布修改</Badge>}
        </span>
      ),
    },
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
          {/* 发布按钮：从未发布时必须能发；已发布且草稿有改动时提示可发；与线上一致时禁用（点了也是 unchanged） */}
          {(r.published_version === null || r.has_unpublished_changes) && (
            <Button size="sm" variant="primary" icon={<Rocket />} onClick={() => onPublish(r)}>发布</Button>
          )}
          {/* 运行：线上没发布时无从运行，禁用并提示（与后端的 403 口径一致，只是提前告诉用户） */}
          <Button size="sm" variant="secondary" icon={<Play />} disabled={!r.node_count || !r.published_version}
            title={r.published_version ? undefined : '工作流还没发布，不能运行'} onClick={() => onRun(r)}>运行</Button>
          <Button size="sm" variant="secondary" icon={<Copy />} onClick={() => onDuplicate(r)}>复制</Button>
          <InlineConfirm message="确定删除？关联的定时任务会一并删除" danger onConfirm={() => onDelete(r)}>
            <Button size="sm" variant="danger">删除</Button>
          </InlineConfirm>
        </span>
      ),
    },
  ]
}
