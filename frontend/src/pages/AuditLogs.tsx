import { Table, Tag } from 'antd'
import { AuditOutlined } from '@ant-design/icons'
import { listAuditLogs } from '../api'
import { usePagedList } from '../hooks/usePagedList'

// 审计日志页：只读表格，无增删改。记录登录、增删改、发布/回滚、RAG 检索等操作轨迹，
// 按操作类型着色；detail 是对象，直接 JSON 序列化展示。
const actionColor: Record<string, string> = {
  login: 'green', login_failed: 'red', create: 'blue', delete: 'red',
  publish: 'orange', update: 'orange', rollback: 'orange', rag_retrieve: 'cyan',
}

export default function AuditLogs() {
  const { tableProps } = usePagedList(listAuditLogs)

  const columns = [
    { title: 'ID', dataIndex: 'id', width: 70 },
    { title: '时间', dataIndex: 'created_at', width: 180, render: (v: string) => v ? new Date(v).toLocaleString() : '-' },
    { title: '用户', dataIndex: 'username', width: 120 },
    { title: '操作', dataIndex: 'action', width: 110, render: (v: string) => <Tag color={actionColor[v] || 'default'}>{v}</Tag> },
    { title: '资源', dataIndex: 'resource', width: 110 },
    { title: '资源ID', dataIndex: 'resource_id', width: 90 },
    { title: '详情', dataIndex: 'detail', ellipsis: true, render: (v: any) => JSON.stringify(v) },
    { title: 'IP', dataIndex: 'ip', width: 130, render: (v: string) => v || '-' },
  ]

  return (
    <div style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column', gap: 16 }}>
      <div style={{ flexShrink: 0 }}>
        <h2 style={{ display: 'flex', alignItems: 'center', gap: 8 }}><AuditOutlined /> 审计日志</h2>
      </div>
      <div className="fixed-table-wrapper">
        <Table rowKey="id" {...tableProps} columns={columns} scroll={{ x: 'max-content' }} />
      </div>
    </div>
  )
}
