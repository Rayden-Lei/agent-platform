import { Play } from 'lucide-react'
import { Link } from 'react-router-dom'
import type { ScheduleRow } from '../../api'
import type { DataColumn } from '../table/DataTable'
import Badge from '../ui/Badge'
import Button from '../ui/Button'
import InlineConfirm from '../ui/InlineConfirm'
import EnableSwitch from '../common/EnableSwitch'
import ResourceLink from '../common/ResourceLink'
import StatusTag from '../common/StatusTag'
import TimeCell from '../common/TimeCell'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/shadcn/tooltip'

interface Options {
  schedulerRunning: boolean
  onOpen: (s: ScheduleRow) => void
  onToggle: (s: ScheduleRow) => Promise<unknown>
  onRunNow: (s: ScheduleRow) => void
  onEdit: (s: ScheduleRow) => void
  onDelete: (s: ScheduleRow) => void
}

// 下次运行列：启用且注册成功才有时间；否则说明原因（停用 / cron 非法 / 调度器未运行）
export function NextRunCell({ row, schedulerRunning }: { row: ScheduleRow; schedulerRunning: boolean }) {
  if (row.next_run_at) return <TimeCell value={row.next_run_at} mode="relative" />
  if (!row.is_enabled) return <span className="text-muted-foreground">已停用</span>
  if (!row.cron_valid) return <Badge tone="danger">cron 非法</Badge>
  if (!schedulerRunning) {
    return (
      <Tooltip>
        <TooltipTrigger asChild><span><Badge tone="warning">调度器未运行</Badge></span></TooltipTrigger>
        <TooltipContent>本进程调度器未运行，任务不会触发</TooltipContent>
      </Tooltip>
    )
  }
  return (
    <Tooltip>
      <TooltipTrigger asChild><span><Badge tone="warning">未注册</Badge></span></TooltipTrigger>
      <TooltipContent>调度器里没有这个任务的注册，重启后端或重新启用一次</TooltipContent>
    </Tooltip>
  )
}

// 定时任务列表列定义：工作流可跳转；cron 非法标红；最近运行给运行记录链接与状态；立即运行 / 编辑 / 删除。
export function buildScheduleColumns({ schedulerRunning, onOpen, onToggle, onRunNow, onEdit, onDelete }: Options): DataColumn<ScheduleRow>[] {
  return [
    { key: 'id', header: 'ID', width: 64, sortable: true, cell: (r) => <span className="text-muted-foreground">{r.id}</span> },
    {
      key: 'name', header: '名称', primary: true, sortable: true, width: 220,
      cell: (r) => <button type="button" onClick={() => onOpen(r)} className="truncate text-left font-medium text-primary hover:underline">{r.name}</button>,
    },
    { key: 'workflow_id', header: '工作流', width: 160, hideOnMobile: true, cell: (r) => <ResourceLink type="workflow" id={r.workflow_id} name={r.workflow_name || `#${r.workflow_id}`} /> },
    {
      key: 'cron', header: 'Cron', width: 150,
      cell: (r) => (
        <span className="inline-flex items-center gap-1">
          <code className="font-mono text-[12.5px]">{r.cron}</code>
          {!r.cron_valid && <Badge tone="danger">非法</Badge>}
        </span>
      ),
    },
    { key: 'status', header: '状态', width: 80, cell: (r) => <EnableSwitch checked={r.is_enabled} onToggle={() => onToggle(r)} /> },
    { key: 'next', header: '下次运行', width: 130, hideOnMobile: true, cell: (r) => <NextRunCell row={r} schedulerRunning={schedulerRunning} /> },
    {
      key: 'last_run_at', header: '最近运行', width: 190, sortable: true, hideOnMobile: true,
      cell: (r) => (r.last_run_at ? (
        <span className="inline-flex items-center gap-1">
          {r.last_run_id ? <Link to={`/runs/${r.last_run_id}`} className="text-primary hover:underline">#{r.last_run_id}</Link> : null}
          <StatusTag domain="run" value={r.last_run_status} />
          <TimeCell value={r.last_run_at} mode="relative" />
        </span>
      ) : '-'),
    },
    { key: 'username', header: '创建人', width: 100, hideOnMobile: true, cell: (r) => r.username || <span className="text-muted-foreground">-</span> },
    {
      key: 'actions', header: '操作', width: 240, pinRight: true,
      cell: (r) => (
        <span className="inline-flex items-center gap-1.5" onClick={(e) => e.stopPropagation()}>
          <InlineConfirm message="立即触发一次？会按任务的固定输入运行工作流" onConfirm={() => onRunNow(r)} confirmLabel="触发">
            <Button size="sm" variant="ghost" icon={<Play />}>立即运行</Button>
          </InlineConfirm>
          <Button size="sm" variant="secondary" onClick={() => onEdit(r)}>编辑</Button>
          <InlineConfirm message="确定删除该定时任务？" onConfirm={() => onDelete(r)}>
            <Button size="sm" variant="danger">删除</Button>
          </InlineConfirm>
        </span>
      ),
    },
  ]
}
