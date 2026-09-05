import { Button, Popconfirm, Space, Tag, Tooltip } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { PlayCircleOutlined } from '@ant-design/icons'
import { Link } from 'react-router-dom'
import type { ScheduleRow } from '../../api'
import EnableSwitch from '../common/EnableSwitch'
import ResourceLink from '../common/ResourceLink'
import StatusTag from '../common/StatusTag'
import TimeCell from '../common/TimeCell'

interface Options {
  sortProps: (field: string) => { sorter: true; sortOrder: 'ascend' | 'descend' | null }
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
  if (!row.is_enabled) return <span style={{ color: '#9ca3af' }}>已停用</span>
  if (!row.cron_valid) return <Tag color="error">cron 非法</Tag>
  if (!schedulerRunning) return <Tooltip title="本进程调度器未运行，任务不会触发"><Tag color="warning">调度器未运行</Tag></Tooltip>
  return <Tooltip title="调度器里没有这个任务的注册，重启后端或重新启用一次"><Tag color="warning">未注册</Tag></Tooltip>
}

// 定时任务列表列定义：工作流可跳转；cron 非法标红；最近运行给运行记录链接与状态；立即运行 / 编辑 / 删除。
export function buildScheduleColumns({ sortProps, schedulerRunning, onOpen, onToggle, onRunNow, onEdit, onDelete }: Options): ColumnsType<ScheduleRow> {
  return [
    { title: 'ID', dataIndex: 'id', key: 'id', width: 60, ...sortProps('id') },
    { title: '名称', dataIndex: 'name', key: 'name', ...sortProps('name'), ellipsis: true, render: (v: string, r) => <a onClick={() => onOpen(r)}>{v}</a> },
    { title: '工作流', dataIndex: 'workflow_id', width: 160, ellipsis: true, render: (v: number, r) => <ResourceLink type="workflow" id={v} name={r.workflow_name || `#${v}`} /> },
    { title: 'Cron', dataIndex: 'cron', width: 150, render: (v: string, r) => <Space size={4}><span style={{ fontFamily: 'monospace' }}>{v}</span>{!r.cron_valid && <Tag color="error">非法</Tag>}</Space> },
    { title: '状态', key: 'status', width: 80, render: (_, r) => <EnableSwitch checked={r.is_enabled} onToggle={() => onToggle(r)} /> },
    { title: '下次运行', key: 'next', width: 130, render: (_, r) => <NextRunCell row={r} schedulerRunning={schedulerRunning} /> },
    {
      title: '最近运行', dataIndex: 'last_run_at', key: 'last_run_at', width: 190, ...sortProps('last_run_at'),
      render: (v: string | null, r) => (v ? <Space size={4}>{r.last_run_id ? <Link to={`/runs/${r.last_run_id}`}>#{r.last_run_id}</Link> : null}<StatusTag domain="run" value={r.last_run_status} /><TimeCell value={v} mode="relative" /></Space> : '-'),
    },
    { title: '创建人', dataIndex: 'username', width: 100, render: (v: string | null) => v || '-' },
    {
      title: '操作', key: 'actions', width: 230, fixed: 'right',
      render: (_, r) => (
        <Space size={4}>
          <Popconfirm title="立即触发一次？会按任务的固定输入运行工作流" onConfirm={() => onRunNow(r)}><Button size="small" icon={<PlayCircleOutlined />}>立即运行</Button></Popconfirm>
          <Button size="small" onClick={() => onEdit(r)}>编辑</Button>
          <Popconfirm title="确定删除该定时任务？" onConfirm={() => onDelete(r)}><Button size="small" danger>删除</Button></Popconfirm>
        </Space>
      ),
    },
  ]
}
