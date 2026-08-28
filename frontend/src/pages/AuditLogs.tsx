import { useEffect, useState } from 'react'
import { Table, Tag, message } from 'antd'
import { AuditOutlined } from '@ant-design/icons'
import { listAuditLogs } from '../api'

const actionColor: Record<string, string> = {
  login: 'green', login_failed: 'red', create: 'blue', delete: 'red',
  publish: 'purple', update: 'orange', rollback: 'orange',
}

export default function AuditLogs() {
  const [data, setData] = useState<any[]>([])
  const [loading, setLoading] = useState(false)

  const load = async () => {
    setLoading(true)
    try { setData(await listAuditLogs() as any) } catch (e: any) { message.error(e.response?.data?.detail || '加载失败') } finally { setLoading(false) }
  }
  useEffect(() => { load() }, [])

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
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', gap: 16 }}>
      <div style={{ flexShrink: 0 }}>
        <h2 style={{ display: 'flex', alignItems: 'center', gap: 8 }}><AuditOutlined /> 审计日志</h2>
      </div>
      <div className="fixed-table-wrapper">
        <Table rowKey="id" loading={loading} dataSource={data} columns={columns} scroll={{ x: 'max-content' }} pagination={{ position: ['bottomRight'], showSizeChanger: true, showTotal: (t) => '共 ' + t + ' 条' }} />
      </div>
    </div>
  )
}
