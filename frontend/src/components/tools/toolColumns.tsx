import { Button, Popconfirm, Space, Tag, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { ExperimentOutlined } from '@ant-design/icons'
import { Link } from 'react-router-dom'
import type { ToolRow } from '../../api'
import EnableSwitch from '../common/EnableSwitch'
import StatusTag from '../common/StatusTag'

interface Options {
  sortProps: (field: string) => { sorter: true; sortOrder: 'ascend' | 'descend' | null }
  canManage: boolean
  onOpen: (tool: ToolRow) => void
  onToggle: (tool: ToolRow) => Promise<unknown>
  onTest: (tool: ToolRow) => void
  onEdit: (tool: ToolRow) => void
  onDelete: (tool: ToolRow) => void
}

export const paramCount = (r: ToolRow) => Object.keys(r.config?.parameters?.properties || {}).length

// 工具列表列定义：名称打开抽屉；HTTP 工具显示方法与地址；未声明参数的 HTTP 工具模型只能空参调用，标黄提醒。
export function buildToolColumns({ sortProps, canManage, onOpen, onToggle, onTest, onEdit, onDelete }: Options): ColumnsType<ToolRow> {
  return [
    { title: 'ID', dataIndex: 'id', key: 'id', width: 60, ...sortProps('id') },
    { title: '名称', dataIndex: 'name', key: 'name', ...sortProps('name'), ellipsis: true, render: (v: string, r) => <a onClick={() => onOpen(r)}>{v}</a> },
    {
      title: '类型', dataIndex: 'type', key: 'type', width: 170, ...sortProps('type'),
      render: (v: string, r) => (
        <Space size={4}>
          <StatusTag domain="toolType" value={v} />
          {v === 'http' && (paramCount(r) ? <Tag>{paramCount(r)} 个参数</Tag> : <Tag color="warning">未声明参数</Tag>)}
        </Space>
      ),
    },
    { title: '描述', dataIndex: 'description', ellipsis: true },
    {
      title: '请求', key: 'request', width: 260, ellipsis: true,
      render: (_, r) => (r.type === 'http' ? <Space size={4}><Tag style={{ marginInlineEnd: 0 }}>{(r.config?.method || 'POST').toUpperCase()}</Tag><Typography.Text ellipsis style={{ maxWidth: 190 }} title={r.config?.url}>{r.config?.url || '-'}</Typography.Text></Space> : <Typography.Text type="secondary">服务内置实现</Typography.Text>),
    },
    { title: '超时', dataIndex: 'timeout', width: 70, align: 'right', render: (v: number) => `${v}s` },
    { title: '状态', key: 'status', width: 80, render: (_, r) => <EnableSwitch checked={r.is_enabled} disabled={!canManage} onToggle={() => onToggle(r)} /> },
    { title: '智能体', dataIndex: 'agents_count', width: 80, align: 'right', render: (v: number, r) => (v ? <Link to={`/agents?tool_id=${r.id}`}>{v}</Link> : '0') },
    {
      title: '操作', key: 'actions', width: 200, fixed: 'right',
      render: (_, r) => (
        <Space size={4}>
          <Button size="small" icon={<ExperimentOutlined />} onClick={() => onTest(r)}>测试</Button>
          <Button size="small" disabled={!canManage} onClick={() => onEdit(r)}>编辑</Button>
          <Popconfirm title="确定删除？绑定了该工具的智能体会失去这项能力" onConfirm={() => onDelete(r)} disabled={!canManage}><Button size="small" danger disabled={!canManage}>删除</Button></Popconfirm>
        </Space>
      ),
    },
  ]
}
