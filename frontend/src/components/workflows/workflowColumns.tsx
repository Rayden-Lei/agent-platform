import { Button, Popconfirm, Space, Tag, Tooltip } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { CopyOutlined, EditOutlined, PlayCircleOutlined } from '@ant-design/icons'
import { Link } from 'react-router-dom'
import type { WorkflowRow } from '../../api'
import StatusTag from '../common/StatusTag'
import TimeCell from '../common/TimeCell'
import { paletteOf } from '../../pages/workflow/palette'

interface Options {
  sortProps: (field: string) => { sorter: true; sortOrder: 'ascend' | 'descend' | null }
  onRun: (wf: WorkflowRow) => void
  onDuplicate: (wf: WorkflowRow) => void
  onDelete: (wf: WorkflowRow) => void
}

// 节点类型统计的中文摘要：把 {agent: 2, tool: 1} 变成 "智能体 2 · 工具 1"
export function nodeTypeSummary(types: Record<string, number>): string {
  return Object.entries(types || {}).map(([t, n]) => `${paletteOf(t)?.label ?? t} ${n}`).join(' · ')
}

// 工作流列表列定义：名称进详情页；节点列显示数量与类型构成；近 7 天运行可跳运行记录。
export function buildWorkflowColumns({ sortProps, onRun, onDuplicate, onDelete }: Options): ColumnsType<WorkflowRow> {
  return [
    { title: 'ID', dataIndex: 'id', key: 'id', width: 60, ...sortProps('id') },
    { title: '名称', dataIndex: 'name', key: 'name', ...sortProps('name'), ellipsis: true, render: (v: string, r) => <Link to={`/workflows/${r.id}`}>{v}</Link> },
    { title: '描述', dataIndex: 'description', ellipsis: true, render: (v: string | null) => v || '-' },
    { title: '状态', dataIndex: 'status', key: 'status', width: 90, ...sortProps('status'), render: (v: string) => <StatusTag domain="workflow" value={v} /> },
    { title: '版本', dataIndex: 'version', width: 70, render: (v: number) => `v${v}` },
    {
      title: '节点', dataIndex: 'node_count', width: 90, align: 'right',
      render: (v: number, r) => (v ? <Tooltip title={nodeTypeSummary(r.node_types)}><span style={{ cursor: 'help' }}>{v}</span></Tooltip> : <Tag>空图</Tag>),
    },
    { title: '定时任务', dataIndex: 'schedules_count', width: 90, align: 'right', render: (v: number) => (v ? <span>{v}</span> : '-') },
    { title: '近 7 天运行', dataIndex: 'runs_7d', width: 110, align: 'right', render: (v: number, r) => (v ? <Link to={`/runs?workflow_id=${r.id}`}>{v}</Link> : '0') },
    { title: '最近运行', dataIndex: 'last_run_at', width: 110, render: (v: string | null) => <TimeCell value={v} mode="relative" /> },
    { title: '创建人', dataIndex: 'created_by_username', width: 100, render: (v: string | null) => v || '-' },
    { title: '更新时间', dataIndex: 'updated_at', key: 'updated_at', width: 170, ...sortProps('updated_at'), render: (v: string | null) => <TimeCell value={v} /> },
    {
      title: '操作', key: 'actions', width: 280, fixed: 'right',
      render: (_, r) => (
        <Space size={4}>
          <Link to={`/workflows/${r.id}/edit`}><Button size="small" icon={<EditOutlined />}>编辑</Button></Link>
          <Button size="small" icon={<PlayCircleOutlined />} disabled={!r.node_count} onClick={() => onRun(r)}>运行</Button>
          <Button size="small" icon={<CopyOutlined />} onClick={() => onDuplicate(r)}>复制</Button>
          <Popconfirm title="确定删除？关联的定时任务会一并删除" onConfirm={() => onDelete(r)}><Button size="small" danger>删除</Button></Popconfirm>
        </Space>
      ),
    },
  ]
}
