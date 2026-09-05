import { Button, Popconfirm, Space, Tag, Tooltip } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { FolderOpenOutlined } from '@ant-design/icons'
import { Link } from 'react-router-dom'
import type { KnowledgeBaseRow } from '../../api'
import StatusTag from '../common/StatusTag'
import TimeCell from '../common/TimeCell'
import { statusLabel } from '../../constants/status'
import { formatNumber } from '../../utils/format'

interface Options {
  sortProps: (field: string) => { sorter: true; sortOrder: 'ascend' | 'descend' | null }
  onEdit: (kb: KnowledgeBaseRow) => void
  onDelete: (kb: KnowledgeBaseRow) => void
}

// 知识库列表列定义：名称进详情页；文档列显示就绪 / 失败 / 处理中的拆分；切片与 token 总量来自列表接口。
export function buildKbColumns({ sortProps, onEdit, onDelete }: Options): ColumnsType<KnowledgeBaseRow> {
  return [
    { title: 'ID', dataIndex: 'id', key: 'id', width: 60, ...sortProps('id') },
    { title: '名称', dataIndex: 'name', key: 'name', ...sortProps('name'), ellipsis: true, render: (v: string, r) => <Link to={`/knowledge-bases/${r.id}`}>{v}</Link> },
    { title: '描述', dataIndex: 'description', ellipsis: true, render: (v: string | null) => v || '-' },
    {
      title: '权限', dataIndex: 'is_public', width: 150,
      render: (v: boolean, r) => (
        <Space size={4}><StatusTag domain="visibility" value={v} />{!v && (r.visible_roles || []).map((role) => <Tag key={role}>{statusLabel('role', role)}</Tag>)}</Space>
      ),
    },
    {
      title: '文档', key: 'documents', width: 170,
      render: (_, r) => (
        <Space size={4}>
          <span>{r.document_count}</span>
          {r.failed_count > 0 && <Tooltip title="解析失败的文档，进详情页看原因并重新解析"><Tag color="error">失败 {r.failed_count}</Tag></Tooltip>}
          {r.processing_count > 0 && <Tag color="processing">处理中 {r.processing_count}</Tag>}
        </Space>
      ),
    },
    { title: '切片 / Token', key: 'chunks', width: 140, align: 'right', render: (_, r) => `${formatNumber(r.chunk_count)} / ${formatNumber(r.token_count)}` },
    { title: '切片参数', key: 'chunk', width: 110, render: (_, r) => `${r.chunk_size} / ${r.chunk_overlap}` },
    { title: '向量模型', dataIndex: 'embedding_model', width: 160, ellipsis: true },
    { title: '创建人', dataIndex: 'created_by_username', width: 100, render: (v: string | null) => v || '-' },
    { title: '更新时间', dataIndex: 'updated_at', key: 'updated_at', width: 170, ...sortProps('updated_at'), render: (v: string | null) => <TimeCell value={v} /> },
    {
      title: '操作', key: 'actions', width: 200, fixed: 'right',
      render: (_, r) => (
        <Space size={4}>
          <Link to={`/knowledge-bases/${r.id}`}><Button size="small" icon={<FolderOpenOutlined />}>文档</Button></Link>
          <Button size="small" onClick={() => onEdit(r)}>编辑</Button>
          <Popconfirm title="确定删除？文档与切片会一并删除" onConfirm={() => onDelete(r)}><Button size="small" danger>删除</Button></Popconfirm>
        </Space>
      ),
    },
  ]
}
