import { Button, Popconfirm, Space, Tag, Tooltip } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { HistoryOutlined, MessageOutlined } from '@ant-design/icons'
import { Link } from 'react-router-dom'
import type { AgentRow } from '../../api'
import ResourceLink from '../common/ResourceLink'
import StatusTag from '../common/StatusTag'
import TimeCell from '../common/TimeCell'

// 智能体列表列定义：名称进详情页；模型 / 模板可跳转；工具与知识库显示绑定数；近 7 天运行数与最近运行时间来自列表接口。
interface Options {
  sortProps: (field: string) => { sorter: true; sortOrder: 'ascend' | 'descend' | null }
  onChat: (a: AgentRow) => void
  onPublish: (a: AgentRow) => void
  onEdit: (a: AgentRow) => void
  onDelete: (a: AgentRow) => void
}

export function buildAgentColumns({ sortProps, onChat, onPublish, onEdit, onDelete }: Options): ColumnsType<AgentRow> {
  return [
    { title: 'ID', dataIndex: 'id', key: 'id', width: 60, ...sortProps('id') },
    {
      title: '名称', dataIndex: 'name', key: 'name', ...sortProps('name'), ellipsis: true,
      render: (v: string, r) => (
        <Space size={4}>
          <Link to={`/agents/${r.id}`}>{v}</Link>
          {/* 模板改版不自动传播：提示开发者重新保存以按最新版本渲染 */}
          {r.prompt_template_outdated && <Tooltip title="绑定的提示词模板已有新版本，重新保存即按最新版本渲染"><Tag color="orange">模板有新版本</Tag></Tooltip>}
        </Space>
      ),
    },
    { title: '状态', dataIndex: 'status', key: 'status', width: 100, ...sortProps('status'), render: (v: string) => <StatusTag domain="agent" value={v} /> },
    { title: '模型', dataIndex: 'model_name', width: 160, ellipsis: true, render: (v: string | null, r) => <ResourceLink type="model" id={r.model_id} name={v} /> },
    {
      title: '能力', key: 'bindings', width: 200,
      render: (_, r) => (
        <Space size={4} wrap>
          <Tooltip title="绑定的工具数"><Tag>工具 {r.tool_ids?.length ?? 0}</Tag></Tooltip>
          <Tooltip title="绑定的知识库数"><Tag>知识库 {r.kb_ids?.length ?? 0}</Tag></Tooltip>
          {r.prompt_template_id && <ResourceLink type="template" id={r.prompt_template_id} name={r.prompt_template_name ? `模板：${r.prompt_template_name}` : '模板'} />}
        </Space>
      ),
    },
    { title: '近 7 天运行', dataIndex: 'runs_7d', width: 110, align: 'right', render: (v: number, r) => (v ? <Link to={`/runs?agent_id=${r.id}`}>{v}</Link> : <span style={{ color: '#9ca3af' }}>0</span>) },
    { title: '最近运行', dataIndex: 'last_run_at', width: 110, render: (v: string | null) => <TimeCell value={v} mode="relative" /> },
    { title: '版本', dataIndex: 'version', key: 'version', width: 70, ...sortProps('version'), render: (v: number) => `v${v}` },
    { title: '创建人', dataIndex: 'created_by_username', width: 100, render: (v: string | null) => v || '-' },
    { title: '更新时间', dataIndex: 'updated_at', key: 'updated_at', width: 170, ...sortProps('updated_at'), render: (v: string | null) => <TimeCell value={v} /> },
    {
      title: '操作', key: 'actions', width: 260, fixed: 'right',
      render: (_, r) => (
        <Space size={4}>
          <Button size="small" icon={<MessageOutlined />} disabled={r.status !== 'published'} onClick={() => onChat(r)}>对话</Button>
          {r.status !== 'published' && <Button size="small" type="primary" onClick={() => onPublish(r)}>发布</Button>}
          <Button size="small" icon={<HistoryOutlined />} onClick={() => onEdit(r)}>编辑</Button>
          <Popconfirm title="确定删除？会话、消息与运行记录会一并删除" onConfirm={() => onDelete(r)}><Button size="small" danger>删除</Button></Popconfirm>
        </Space>
      ),
    },
  ]
}
