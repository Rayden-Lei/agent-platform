import { Button, Popconfirm, Space, Tag, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { Link } from 'react-router-dom'
import type { PromptTemplateRow } from '../../api'
import TimeCell from '../common/TimeCell'

interface Options {
  sortProps: (field: string) => { sorter: true; sortOrder: 'ascend' | 'descend' | null }
  onOpen: (t: PromptTemplateRow) => void
  onEdit: (t: PromptTemplateRow) => void
  onDelete: (t: PromptTemplateRow) => void
}

// 模板列表列定义：名称打开抽屉；变量列标出必填；智能体数可跳到按模板筛选的智能体列表。
export function buildTemplateColumns({ sortProps, onOpen, onEdit, onDelete }: Options): ColumnsType<PromptTemplateRow> {
  return [
    { title: 'ID', dataIndex: 'id', key: 'id', width: 60, ...sortProps('id') },
    { title: '名称', dataIndex: 'name', key: 'name', ...sortProps('name'), ellipsis: true, render: (v: string, r) => <a onClick={() => onOpen(r)}>{v}</a> },
    { title: '描述', dataIndex: 'description', ellipsis: true, render: (v: string | null) => v || '-' },
    {
      title: '变量', dataIndex: 'variables', width: 260,
      render: (vars: PromptTemplateRow['variables']) => (vars.length ? <Space size={4} wrap>{vars.map((v) => <Tag key={v.name}>{v.name}{v.required ? ' *' : ''}</Tag>)}</Space> : <Typography.Text type="secondary">无</Typography.Text>),
    },
    { title: '版本', dataIndex: 'version', key: 'version', width: 80, ...sortProps('version'), render: (v: number) => `v${v}` },
    { title: '智能体', dataIndex: 'agents_count', width: 80, align: 'right', render: (v: number | undefined, r) => (v ? <Link to={`/agents?prompt_template_id=${r.id}`}>{v}</Link> : '0') },
    { title: '创建人', dataIndex: 'created_by_username', width: 100, render: (v: string | null | undefined) => v || '-' },
    { title: '更新时间', dataIndex: 'updated_at', key: 'updated_at', width: 170, ...sortProps('updated_at'), render: (v: string) => <TimeCell value={v} /> },
    {
      title: '操作', key: 'actions', width: 150, fixed: 'right',
      render: (_, r) => (
        <Space size={4}>
          <Button size="small" onClick={() => onEdit(r)}>编辑</Button>
          {/* 仍被智能体绑定时后端 409，提示里带绑定数 */}
          <Popconfirm title="确定删除？仍被智能体绑定时会被拒绝" onConfirm={() => onDelete(r)}><Button size="small" danger>删除</Button></Popconfirm>
        </Space>
      ),
    },
  ]
}
